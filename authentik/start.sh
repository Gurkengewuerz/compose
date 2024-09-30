#!/bin/bash

# Set the path to the HTML file(s)
TEMPLATE_DIR="/authentik/flows/templates/if"
TEMPLATE_FILE="$TEMPLATE_DIR/*.html"

# 1. Append a custom CSS tag in the block head
# This will append '<link rel="stylesheet" href="/path/to/custom.css">' just before the block head ends
sed -i '/{% block head %}/a <link rel="stylesheet" href="/media/custom/flow/custom.css" data-inject>' $TEMPLATE_FILE

# 2. Remove the `--ak-flow-background` variable in :root
# This will remove any line containing '--ak-flow-background' from the CSS in the HTML files
sed -i '/--ak-flow-background/d' $TEMPLATE_FILE

# 3. Execute the original command
dumb-init -- /lifecycle/ak "$1"
