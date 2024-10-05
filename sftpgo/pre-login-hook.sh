#!/bin/bash
##
##========================================================================================
##                                                                                      ##
##                       SFTPGO: Create a user on OIDC connection                       ##
##                                   with a S3 backend                                  ##
##                                                                                      ##
##========================================================================================


##──── VARIABLES ─────────────────────────────────────────────────────────────────────────

## The template for the user to create
##
## the variable style strings ($username...) are placeholders for jq
## cf: USER_TO_CREATE below
##
### fields are :
##
### status: 0 or 1 (inactive or active)
### username: depending on your OIDC settings, it can be an email address, a surname...
### password (optional): if you want to set a password for this user to connect via FTP/SFTP/WEBDAV...
### permissions: set of permissions for this user (called ACLs in the UI)
### filesystem: 
#### provider: `0` for local filesystem, `1` for S3 backend, `2` for Google Cloud Storage (GCS) backend, `3` for Azure Blob Storage backend, `4` for local encrypted backend, `5` for SFTP backend
SFTPGO_USER_TEMPLATE='{
  "status": 1, 
  "username": $username, 
  "description": "OIDC user",
  "quota_size": $quota,
  "permissions": {
    "/":["*"]
    }, 
  "filesystem": {
    "provider": 0, 
      }
    }'


##──── INTERNAL VARIABLES ────────────────────────────────────────────────────────────────

## The current user ID
##
CURR_USER_ID=$(echo "${SFTPGO_LOGIND_USER}" | jq -r .id)

## The custom fold for Quota
##
CURR_USER_QUOTA=$(echo "${SFTPGO_LOGIND_USER}" | jq -r .oidc_custom_fields.sftpgo_quota)

## The current user name
##
CURR_USER_NAME=$(echo "${SFTPGO_LOGIND_USER}" | jq -r .username)

cleaned_size=$(echo "$CURR_USER_QUOTA" | sed 's/B//g')
bytes=$(numfmt --from=si --to=none $cleaned_size)

## The user to create, serialized in JSON
##
USER_TO_CREATE=$(jq --null-input \
--arg username "${CURR_USER_NAME}" \
--argjson quota "${bytes}" \
"${SFTPGO_USER_TEMPLATE}")


##──── LOGIC ─────────────────────────────────────────────────────────────────────────────

echo "Running Pre Login Hook for $CURR_USER_ID" >&2

## Is the user coming from an OIDC connection ?
if [[ "${SFTPGO_LOGIND_METHOD,,}" != "idp" || "${SFTPGO_LOGIND_PROTOCOL,,}" != "oidc" ]]
then
    echo "The user is not coming from an external IDP or is not connecting via OIDC" >&2
    exit 0

## Does the user already exist in SFTPGo ?
### if it's equal to 0, the user DOESN'T exist inside SFTPGo
elif [[ "${CURR_USER_ID}" -ne 0 ]]
then
    echo "The user already exists in SFTPGo" >&2
    exit 0

## Return the user for it to be created automatically
else
    echo $USER_TO_CREATE >&2
    echo "${USER_TO_CREATE}"
    exit 0
fi
