#!/usr/bin/with-contenv bash
# shellcheck shell=bash

# fix for replys when using a relay server
# see https://github.com/anonaddy/docker/issues/284

set -e

. $(dirname $0)/00-env

# Script to add DMARC "Allow" header if the email passes the DMARC policy check
HEADER_FILE="/etc/postfix/header_checks"

# Ensure the header checks file exists
if [ ! -f "$HEADER_FILE" ]; then
    echo "/^From:/ PREPEND X-AnonAddy-Dmarc-Allow: Yes" > "$HEADER_FILE"
else
    if ! grep -q "X-AnonAddy-Dmarc-Allow" "$HEADER_FILE"; then
        echo "/^From:/ PREPEND X-AnonAddy-Dmarc-Allow: Yes" >> "$HEADER_FILE"
    fi
fi

# Update Postfix configuration to include header checks
postconf -e "header_checks = regexp:$HEADER_FILE"

