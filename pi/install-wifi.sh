#!/bin/sh
# Install only the Pi image Wi-Fi helper and its exact no-argument permission.
set -eu
cd "$(dirname "$0")/.."
if [ "$(id -u)" = 0 ]; then
    echo 'Run as the normal YAC user, without sudo before the script.'
    exit 1
fi
command -v nmcli >/dev/null
command -v raspi-config >/dev/null
sudo install -d -m 755 /usr/local/libexec
sudo install -m 755 pi/wifi-settings.py /usr/local/libexec/yac-pi-wifi
sudo install -d -m 755 /usr/local/sbin
sudo install -m 755 pi/clear-image-wifi.py /usr/local/sbin/yac-image-clear-wifi
account=$(id -un)
case "$account" in
    *[!a-zA-Z0-9_-]*|'') echo 'Account name needs manual sudoers configuration.'; exit 1 ;;
esac
policy=$(mktemp)
trap 'rm -f "$policy"' EXIT HUP INT TERM
printf '%s ALL=(root) NOPASSWD: /usr/local/libexec/yac-pi-wifi ""\n' "$account" > "$policy"
sudo /usr/sbin/visudo -cf "$policy"
sudo install -m 440 "$policy" /etc/sudoers.d/yac-pi-wifi
echo 'Pi Wi-Fi helper installed. Updated YAC provides s w on image launches.'
