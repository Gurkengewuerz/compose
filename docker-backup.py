#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#----------------------------------------------------------------------------
# Created By  : Gurkengewuerz <niklas@mc8051.de>
# Created Date: 01.10.2022
# License     : GNU AGPL v3 
# ---------------------------------------------------------------------------

# 0 4 * * * /usr/bin/python3 /home/user/deployment/docker-backup.py > /tmp/backup.log

# pip install docker
import docker
# pip install requests
import requests
import os
import subprocess
import sys

# pip install python-dotenv
from dotenv import dotenv_values
# pip install webdavclient3
from webdav3.client import Client
from getpass import getpass
from urllib.parse import urlparse

ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")

if not os.path.isfile(ENV_PATH) or not os.access(ENV_PATH, os.R_OK):
  print(f"Failure: reading {ENV_PATH} failed")
  sys.exit(1)

VIRTENV_VARS = dotenv_values(ENV_PATH)

BACKUP_BIN = VIRTENV_VARS["BACKUP_BIN"]
if BACKUP_BIN is None or BACKUP_BIN == "":
  print(f"Failure: binary {BACKUP_BIN} not found")
  sys.exit(1)
if not os.access(BACKUP_BIN, os.R_OK) or not os.access(BACKUP_BIN, os.X_OK):
  print(f"Failure: wrong permissions on {BACKUP_BIN}")
  sys.exit(1)

if VIRTENV_VARS["WEBDAV_REPO"] is None or VIRTENV_VARS["WEBDAV_REPO"] == "":
  print(f"Failure: could not find WEBDAV_REPO in .env")
  sys.exit(1)

webdav = urlparse(VIRTENV_VARS["WEBDAV_REPO"])

webdav_protocol = webdav.scheme
webdav_username = webdav.username
webdav_password = webdav.password
webdav_netloc = webdav.netloc
webdav_path = webdav.path.rstrip("/")

webdav_opt = {}

if webdav_username and webdav_password:
    webdav_netloc = webdav_netloc.replace(f"{webdav_username}:{webdav_password}@", "")
    VIRTENV_VARS["OPENDAL_USERNAME"] = webdav_username
    VIRTENV_VARS["OPENDAL_PASSWORD"] = webdav_password
    webdav_opt["webdav_login"] = webdav_username
    webdav_opt["webdav_password"] = webdav_password

VIRTENV_VARS["RUSTIC_REPOSITORY"] = "opendal:webdav"
VIRTENV_VARS["WEBDAV_REPO"] = f"{webdav_protocol}://{webdav_netloc}{webdav_path}"
webdav_opt["webdav_hostname"] = VIRTENV_VARS["WEBDAV_REPO"]

webdav_client = Client(webdav_opt)

LABEL_NAMES = {
  "enabled": "backup.enable",
  "password": "backup.password",
  "volumes": "backup.volumes",
  "exclude": "backup.exclude",
  "keep": "backup.keep",
}

def shell():
  repo_url = "{}/{}".format(VIRTENV_VARS["WEBDAV_REPO"], sys.argv[2])
  print("Using repository", repo_url)
  password = getpass("Repository Password: ")
  processEnv = {**os.environ, **VIRTENV_VARS, "RUSTIC_PASSWORD": password, "OPENDAL_ENDPOINT": repo_url}
  print("**********************************")
  print("You have entered a new shell with the correct enviroment variables")
  print("**********************************")
  subprocess.run(["bash"], env=processEnv, start_new_session=True)

def ls():
  for list_dir in webdav_client.list():
    print(list_dir.rstrip("/"))

def send_notification(failed, msg):
  print("Sending Notification")
  # https://github.com/Gurkengewuerz/shoutrrr-api
  shout_api = VIRTENV_VARS.get("SHOUTRRR_API", "").strip()
  shout_token = VIRTENV_VARS.get("SHOUTRRR_TOKEN", "").strip()
  if not shout_api or not shout_token:
    print("pass send_notification() due to no SHOUTRRR API defined")
    return
  hostname = os.uname()[1]
  f_name = os.path.basename(__file__)
  title = f"{f_name} - {hostname}"
  if failed:
    title = "FAILED: " + title
  try:
    r = requests.post(f"{shout_api}/{shout_token}", json={"title": title, "message": msg})
    r.raise_for_status()
  except Error as err:
    print("Failed to send Notification", err)

def run():
  client = docker.APIClient(base_url='unix://var/run/docker.sock')
  
  counter = {
    "total": 0,
    "skipped": 0,
    "success": 0,
    "failed": 0,
  }

  for container in client.containers():
    counter["total"] += 1
    name = container["Names"][0][1:]
    
    for _ in range(5):
      print()

    print("Info: Processing container \"{}\"...".format(name))


    labels = container["Labels"]
    mounts = container["Mounts"]
    workdirs = labels["com.docker.compose.project.working_dir"] if "com.docker.compose.project.working_dir" in labels else ""
    composefile = labels["com.docker.compose.project.config_files"] if "com.docker.compose.project.config_files" in labels else ""

    if len(workdirs) == 0:
      print("Warn: No workdir found. Skipping.")
      counter["skipped"] += 1
      continue

    if len(mounts) == 0:
      print("Info: No mounts found. Skipping.")
      counter["skipped"] += 1
      continue

    if LABEL_NAMES["enabled"] not in labels or labels[LABEL_NAMES["enabled"]] == "False":
      print("Info: Backup not enabled. Skipping.")
      counter["skipped"] += 1
      continue
    
    if LABEL_NAMES["password"] not in labels or len(labels[LABEL_NAMES["password"]]) == 0:
      print("Failure: Password is missing. Skipping.")
      counter["failed"] += 1
      continue
    
    toUpdate = [composefile]
    if LABEL_NAMES["volumes"] not in labels:
      for mount in mounts:
        toUpdate.append(mount["Source"])
    else:
      for vol in labels[LABEL_NAMES["volumes"]].split(","):
        path = vol.replace("./", workdirs + "/").rstrip("/")
        for mount in mounts:
          if mount["Source"] == path:
            toUpdate.append(mount["Source"])
          if "Name" in mount and mount["Name"].endswith(path):
            toUpdate.append(mount["Source"])
   
    keep_last = "14"
    if LABEL_NAMES["keep"] in labels:
      if isinstance(labels[LABEL_NAMES["keep"]], int):
        keep_last = labels[LABEL_NAMES["keep"]]
      else:
        print("Invalid value for {}. Defaulting to backps".format(LABEL_NAMES["keep"], keep_last))
    else:
      print("Defaulting to keep last {} backups".format(keep_last))

    repo_url = "{}/{}".format(VIRTENV_VARS["WEBDAV_REPO"], name)
    print("Repository URL:", repo_url)

    processEnv = {**os.environ, **VIRTENV_VARS, "RUSTIC_PASSWORD": labels[LABEL_NAMES["password"]], "OPENDAL_ENDPOINT": repo_url}
    
    if not webdav_client.check(name):
      try:
        webdav_client.execute_request("mkdir", name)
      except:
        pass

    ## rustic doesn't has return codes, so just try to init
    cmd = [BACKUP_BIN, "init"]
    print("Run init: {}".format(" ".join(cmd)))
    process = subprocess.run(" ".join(cmd), env=processEnv, shell=True)
    if process.returncode == 0:
      print("Success: autoinitialize repository")
    else:
      print("Failure: autoinitialize failed")
      #counter["failed"] += 1
      #continue
    
    excludeList = []
    if LABEL_NAMES["exclude"] in labels:
      for f in labels[LABEL_NAMES["exclude"]].split(","):
        excludeList.append("--glob '{}'".format(f))
    
    print("Running Backup")
    cmd = [BACKUP_BIN, "backup", "--tag", name, *excludeList, *toUpdate]
    print("Run backup: {}".format(" ".join(cmd)))
    process = subprocess.run(" ".join(cmd), env=processEnv, shell=True)
    if process.returncode == 0:
      print("Success: Backup ran successfully. A failure would be not great but not terrible")
    else:
      print("Failure: failed to backup")
      counter["failed"] += 1
      continue
    
    print("Pruning keep last {} backups".format(keep_last))
    process = subprocess.run(" ".join([BACKUP_BIN, "forget", "--keep-last", keep_last, "--prune"]), env=processEnv, shell=True)
    if process.returncode == 0:
      print("Success: removed unwanted snapshots")
    else:
      print("Failure: removing old snapshots failed")

    counter["success"] += 1

  print()
  print()
  print("Backup Stats")
  print("####################")

  stats = "Total processed: {}\n".format(counter["total"])
  stats = stats + "Skipped: {}\n".format(counter["skipped"])
  stats = stats + "Failed: {}\n".format(counter["failed"])
  stats = stats + "Successfully backuped: {}\n".format(counter["success"])

  print(stats)

  send_notification(counter["failed"] > 0, stats)

if __name__ == '__main__':
  if len(sys.argv) == 3 and sys.argv[1] == "shell":
    shell()
  elif len(sys.argv) == 2 and sys.argv[1] == "ls":
    ls()
  elif len(sys.argv) == 1:
    run()
  else:
    print("{} - start backup".format(sys.argv[0]))
    print("{} shell <repository> - start shell for repository".format(sys.argv[0]))
    print("{} ls - list repositories in remote".format(sys.argv[0]))
