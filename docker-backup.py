#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ---------------------------------------------------------------------------
# Created By  : Gurkengewuerz <niklas@mc8051.de>
# Created Date: 01.10.2022
# License     : GNU AGPL v3
# ---------------------------------------------------------------------------

# 0 4 * * * /usr/bin/python3 /home/user/deployment/docker-backup.py > /tmp/backup.log

# pip install docker requests python-dotenv webdavclient3
import docker
import requests
import os
import subprocess
import sys

from dotenv import dotenv_values
from getpass import getpass
from urllib.parse import urlparse

ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")

if not os.path.isfile(ENV_PATH) or not os.access(ENV_PATH, os.R_OK):
    print(f"Failure: reading {ENV_PATH} failed")
    sys.exit(1)

VIRTENV_VARS = dotenv_values(ENV_PATH)

BACKUP_BIN = VIRTENV_VARS.get("BACKUP_BIN", "")
if not BACKUP_BIN:
    print("Failure: BACKUP_BIN not set in .env")
    sys.exit(1)
if not os.access(BACKUP_BIN, os.R_OK) or not os.access(BACKUP_BIN, os.X_OK):
    print(f"Failure: wrong permissions on {BACKUP_BIN}")
    sys.exit(1)

LABEL_NAMES = {
    "enabled": "backup.enable",
    "password": "backup.password",
    "volumes": "backup.volumes",
    "exclude": "backup.exclude",
    "keep": "backup.keep",
}

# ---------------------------------------------------------------------------
# Backend detection and configuration
# ---------------------------------------------------------------------------

BACKEND_TYPE = VIRTENV_VARS.get("BACKEND_TYPE", "").strip().lower()

# Auto-detect backend from legacy WEBDAV_REPO if BACKEND_TYPE is not set
if not BACKEND_TYPE:
    if VIRTENV_VARS.get("WEBDAV_REPO", "").strip():
        BACKEND_TYPE = "webdav"
    elif VIRTENV_VARS.get("S3_ENDPOINT", "").strip() or VIRTENV_VARS.get("S3_BUCKET", "").strip():
        BACKEND_TYPE = "s3"
    else:
        print("Failure: No backend configured. Set BACKEND_TYPE=webdav or BACKEND_TYPE=s3 in .env")
        sys.exit(1)

webdav_client = None  # only initialised for webdav backend


def _configure_webdav():
    """Configure WebDAV backend – returns base repo URL."""
    global webdav_client

    repo_raw = VIRTENV_VARS.get("WEBDAV_REPO", "").strip()
    if not repo_raw:
        print("Failure: could not find WEBDAV_REPO in .env")
        sys.exit(1)

    # lazily import only when needed
    from webdav3.client import Client

    webdav = urlparse(repo_raw)

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

    base_url = f"{webdav_protocol}://{webdav_netloc}{webdav_path}"
    VIRTENV_VARS["RUSTIC_REPOSITORY"] = "opendal:webdav"
    VIRTENV_VARS["WEBDAV_REPO"] = base_url
    webdav_opt["webdav_hostname"] = base_url

    webdav_client = Client(webdav_opt)
    return base_url


def _configure_s3():
    """Configure S3 backend – returns base repo path (bucket/prefix)."""
    s3_bucket = VIRTENV_VARS.get("S3_BUCKET", "").strip()
    if not s3_bucket:
        print("Failure: S3_BUCKET not set in .env")
        sys.exit(1)

    s3_endpoint = VIRTENV_VARS.get("S3_ENDPOINT", "").strip()
    s3_region = VIRTENV_VARS.get("S3_REGION", "").strip()
    s3_access_key = VIRTENV_VARS.get("S3_ACCESS_KEY", "").strip()
    s3_secret_key = VIRTENV_VARS.get("S3_SECRET_KEY", "").strip()
    s3_prefix = VIRTENV_VARS.get("S3_PREFIX", "").strip().strip("/")

    VIRTENV_VARS["RUSTIC_REPOSITORY"] = "opendal:s3"
    VIRTENV_VARS["OPENDAL_BUCKET"] = s3_bucket

    if s3_endpoint:
        VIRTENV_VARS["OPENDAL_ENDPOINT"] = s3_endpoint
    if s3_region:
        VIRTENV_VARS["OPENDAL_REGION"] = s3_region
    if s3_access_key:
        VIRTENV_VARS["OPENDAL_ACCESS_KEY_ID"] = s3_access_key
    if s3_secret_key:
        VIRTENV_VARS["OPENDAL_SECRET_ACCESS_KEY"] = s3_secret_key

    # base path inside the bucket, e.g. "backups/host01"
    return s3_prefix


def _repo_url_for_container(base, container_name):
    """Return the per-container repo URL/path and set the right env var."""
    if BACKEND_TYPE == "webdav":
        url = f"{base}/{container_name}"
        return url, {"OPENDAL_ENDPOINT": url}
    else:
        root = f"{base}/{container_name}" if base else container_name
        return root, {"OPENDAL_ROOT": root}


def _ensure_remote_dir(container_name):
    """Create the remote directory for a container if it doesn't exist (WebDAV only)."""
    if BACKEND_TYPE != "webdav" or webdav_client is None:
        return
    if not webdav_client.check(container_name):
        try:
            webdav_client.execute_request("mkdir", container_name)
        except Exception:
            pass


# Initialise chosen backend
if BACKEND_TYPE == "webdav":
    REPO_BASE = _configure_webdav()
elif BACKEND_TYPE == "s3":
    REPO_BASE = _configure_s3()
else:
    print(f"Failure: unknown BACKEND_TYPE '{BACKEND_TYPE}'. Use 'webdav' or 's3'.")
    sys.exit(1)

print(f"Info: Using backend '{BACKEND_TYPE}'")

# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def shell():
    repo_target = sys.argv[2]
    _, extra_env = _repo_url_for_container(REPO_BASE, repo_target)
    display_url = f"{REPO_BASE}/{repo_target}" if REPO_BASE else repo_target
    print("Using repository", display_url)
    password = getpass("Repository Password: ")
    process_env = {**os.environ, **VIRTENV_VARS, **extra_env, "RUSTIC_PASSWORD": password}
    print("**********************************")
    print("You have entered a new shell with the correct environment variables")
    print("**********************************")
    subprocess.run(["bash"], env=process_env, start_new_session=True)


def ls():
    if BACKEND_TYPE == "webdav" and webdav_client is not None:
        for list_dir in webdav_client.list():
            print(list_dir.rstrip("/"))
    elif BACKEND_TYPE == "s3":
        # Use rustic or a simple listing via opendal env
        print("Listing not directly supported for S3 – use your S3 client or:")
        print(f"  aws s3 ls s3://{VIRTENV_VARS.get('S3_BUCKET', '')}/{REPO_BASE}/")
    else:
        print("No listing method available for this backend.")


def send_notification(failed, msg):
    print("Sending Notification")
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
    except Exception as err:
        print("Failed to send Notification", err)


def run():
    client = docker.APIClient(base_url="unix://var/run/docker.sock")

    counter = {
        "total": 0,
        "skipped": 0,
        "success": 0,
        "failed": 0,
    }

    for container in client.containers():
        counter["total"] += 1
        name = container["Names"][0][1:]

        print(f"\n\n\n\n\nInfo: Processing container \"{name}\"...")

        labels = container["Labels"]
        mounts = container["Mounts"]
        workdirs = labels.get("com.docker.compose.project.working_dir", "")
        composefile = labels.get("com.docker.compose.project.config_files", "")

        if not workdirs:
            print("Warn: No workdir found. Skipping.")
            counter["skipped"] += 1
            continue

        if not mounts:
            print("Info: No mounts found. Skipping.")
            counter["skipped"] += 1
            continue

        if LABEL_NAMES["enabled"] not in labels or labels[LABEL_NAMES["enabled"]] == "False":
            print("Info: Backup not enabled. Skipping.")
            counter["skipped"] += 1
            continue

        if LABEL_NAMES["password"] not in labels or not labels[LABEL_NAMES["password"]]:
            print("Failure: Password is missing. Skipping.")
            counter["failed"] += 1
            continue

        to_update = [f.strip() for f in composefile.split(",") if f.strip()] if composefile else []
        if LABEL_NAMES["volumes"] not in labels:
            for mount in mounts:
                to_update.append(mount["Source"])
        else:
            for vol in labels[LABEL_NAMES["volumes"]].split(","):
                path = vol.replace("./", workdirs + "/").rstrip("/")
                for mount in mounts:
                    if mount["Source"] == path:
                        to_update.append(mount["Source"])
                    if "Name" in mount and mount["Name"].endswith(path):
                        to_update.append(mount["Source"])

        keep_last = "14"
        if LABEL_NAMES["keep"] in labels:
            val = labels[LABEL_NAMES["keep"]]
            if str(val).isdigit():
                keep_last = str(val)
            else:
                print(f"Invalid value for {LABEL_NAMES['keep']}: '{val}'. Defaulting to keep last {keep_last} backups")
        else:
            print(f"Defaulting to keep last {keep_last} backups")

        repo_display, extra_env = _repo_url_for_container(REPO_BASE, name)
        print("Repository:", repo_display)

        process_env = {
            **os.environ,
            **VIRTENV_VARS,
            **extra_env,
            "RUSTIC_PASSWORD": labels[LABEL_NAMES["password"]],
        }

        _ensure_remote_dir(name)

        # rustic init (idempotent – will fail harmlessly if already initialised)
        cmd = [BACKUP_BIN, "init"]
        print(f"Run init: {' '.join(cmd)}")
        process = subprocess.run(cmd, env=process_env)
        if process.returncode == 0:
            print("Success: autoinitialize repository")
        else:
            print("Info: init returned non-zero (repository likely already initialised)")

        exclude_list = []
        if LABEL_NAMES["exclude"] in labels:
            for f in labels[LABEL_NAMES["exclude"]].split(","):
                exclude_list.extend(["--glob", f])

        print("Running Backup")
        cmd = [BACKUP_BIN, "backup", "--tag", name, *exclude_list, *to_update]
        print(f"Run backup: {' '.join(cmd)}")
        process = subprocess.run(cmd, env=process_env)
        if process.returncode == 0:
            print("Success: Backup ran successfully")
        else:
            print("Failure: failed to backup")
            counter["failed"] += 1
            continue

        print(f"Pruning keep last {keep_last} backups")
        cmd = [BACKUP_BIN, "forget", "--keep-last", keep_last, "--prune"]
        process = subprocess.run(cmd, env=process_env)
        if process.returncode == 0:
            print("Success: removed unwanted snapshots")
        else:
            print("Failure: removing old snapshots failed")

        counter["success"] += 1

    print("\n\nBackup Stats")
    print("####################")

    stats = (
        f"Total processed: {counter['total']}\n"
        f"Skipped: {counter['skipped']}\n"
        f"Failed: {counter['failed']}\n"
        f"Successfully backed up: {counter['success']}\n"
    )

    print(stats)
    send_notification(counter["failed"] > 0, stats)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "shell":
        shell()
    elif len(sys.argv) == 2 and sys.argv[1] == "ls":
        ls()
    elif len(sys.argv) == 1:
        run()
    else:
        print(f"{sys.argv[0]} - start backup")
        print(f"{sys.argv[0]} shell <repository> - start shell for repository")
        print(f"{sys.argv[0]} ls - list repositories in remote")
