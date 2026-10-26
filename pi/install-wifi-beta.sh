#!/bin/sh
# Update an existing Pi beta with s u/s w, without touching boot or audio setup.
set -eu
cd "$(dirname "$0")/.."
if [ "$(id -u)" = 0 ]; then
    echo 'Run as the normal YAC user, without sudo before the script.'
    exit 1
fi
echo 'Updating the existing YAC installation. Quit YAC first.'
sh pi/update-source-beta.sh
sh pi/install-wifi.sh
echo 'Wi-Fi beta update finished. Start YAC with your usual Pi launcher.'
