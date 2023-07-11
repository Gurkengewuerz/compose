#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#----------------------------------------------------------------------------
# Created By  : Gurkengewuerz <niklas@mc8051.de>
# Created Date: 01.10.2022
# License     : GNU AGPL v3 
# ---------------------------------------------------------------------------

import subprocess
import docker
import os
import sys

# pip install python-dotenv
from dotenv import dotenv_values
from getpass import getpass

ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")

if not os.path.isfile(ENV_PATH) or not os.access(ENV_PATH, os.R_OK):
  print(f"Failure: reading {ENV_PATH} failed")
  sys.exit(1)

# Requires
# RESTIC_BIN /usr/bin/restic
# RESTIC_REPOSITORY s3:https://s3.amazonaws.com/restic
# AWS_ACCESS_KEY_ID
# AWS_SECRET_ACCESS_KEY
RESTIC_VARS = dotenv_values(ENV_PATH)

RESTIC_BIN = RESTIC_VARS.pop("RESTIC_BIN", None)
if RESTIC_BIN is None or not os.path.isfile(RESTIC_BIN):
  print(f"Failure: restic bin {RESTIC_BIN} not exists or set in .env RESTIC_BIN")
  sys.exit(1)
if not os.access(RESTIC_BIN, os.R_OK) or not os.access(RESTIC_BIN, os.X_OK):
  print(f"Failure: wrong permissions on {RESTIC_BIN}")
  sys.exit(1)

LABEL_NAMES = {
  "enabled": "backup.enable",
  "password": "backup.password",
  "volumes": "backup.volumes",
  "exclude": "backup.exclude",
  "keep": "backup.keep",
}

def shell():
  repo_url = "{}/{}".format(RESTIC_VARS["RESTIC_REPOSITORY"], sys.argv[2])
  print("Using restic repository", repo_url)
  password = getpass("Repository Password: ")
  resticENV = {**os.environ, **RESTIC_VARS, "RESTIC_PASSWORD": password, "RESTIC_REPOSITORY": repo_url}
  print("**********************************")
  print("You have entered a new shell with the correct restic enviroment variables")
  print("**********************************")
  subprocess.run(["bash"], env=resticENV, start_new_session=True)

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
    labels = container["Labels"]
    mounts = container["Mounts"]
    workdirs = labels["com.docker.compose.project.working_dir"]
    
    for _ in range(5):
      print()

    print("Info: Processing container \"{}\"...".format(name))
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

    toUpdate = []
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

    repo_url = "{}/{}".format(RESTIC_VARS["RESTIC_REPOSITORY"], name)
    print("Repository URL:", repo_url)

    resticENV = {**os.environ, **RESTIC_VARS, "RESTIC_PASSWORD": labels[LABEL_NAMES["password"]], "RESTIC_REPOSITORY": repo_url}
    
    process = subprocess.run(" ".join([RESTIC_BIN, "cat", "config"]), env=resticENV, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if process.returncode == 0:
      print("Info: restic repository already initialized.")
    else:
      print("Warn: restic repository not initialized. autoinitialize now")
      process = subprocess.run(" ".join([RESTIC_BIN, "init"]), env=resticENV, shell=True)
      if process.returncode == 0:
        print("Success: autoinitialize repository")
      else:
        print("Failure: autoinitialize failed")
        counter["failed"] += 1
        continue
    
    excludeList = []
    if LABEL_NAMES["exclude"] in labels:
      for f in labels[LABEL_NAMES["exclude"]].split(","):
        excludeList.append("--exclude '{}'".format(f))
    
    cmd = [RESTIC_BIN, "backup", "--tag", name, *excludeList, *toUpdate]
    print("Run backup: {}".format(" ".join(cmd)))
    process = subprocess.run(" ".join(cmd), env=resticENV, shell=True)
    if process.returncode == 0:
      print("Success: Backup ran successfully. A failure would be not great but not terrible")
    else:
      print("Failure: failed to backup")
      counter["failed"] += 1
      continue

    process = subprocess.run(" ".join([RESTIC_BIN, "forget", "--keep-last", keep_last, "--prune"]), env=resticENV, shell=True)
    if process.returncode == 0:
      print("Success: removed unwanted snapshots")
    else:
      print("Failure: removing old snapshots failed")

    counter["success"] += 1

  print()
  print()
  print("Backup Stats")
  print("####################")
  print("Total processed: {}".format(counter["total"]))
  print("Skipped: {}".format(counter["skipped"]))
  print("Failed: {}".format(counter["failed"]))
  print("Successfully backuped: {}".format(counter["success"]))
  
if __name__ == '__main__':
  if len(sys.argv) == 3 and sys.argv[1] == "shell":
    shell()
  elif len(sys.argv) == 1:
    run()
  else:
    print("{} - start backup".format(sys.argv[0]))
    print("{} shell <repository> - start shell for repository".format(sys.argv[0]))
