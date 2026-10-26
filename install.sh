#!/bin/sh
# Complete Pi update. Run as the normal login user: sh install.sh
set -eu
cd "$(dirname "$0")"
[ "$(uname -s)" = Linux ] || { echo 'Run this installer on the Pi.'; exit 1; }
[ "$(id -u)" != 0 ] || { echo 'Run sh install.sh without sudo.'; exit 1; }
for tool in python3 sudo nmcli raspi-config; do
    command -v "$tool" >/dev/null || { echo "Missing required command: $tool"; exit 1; }
done
account=$(id -un)
case "$account" in *[!a-zA-Z0-9_-]*|'') echo 'Unsupported account name.'; exit 1 ;; esac
policy=$(mktemp)
trap 'rm -f "$policy"' EXIT HUP INT TERM
printf '%s ALL=(root) NOPASSWD: /usr/local/libexec/yac-pi-audio "", /usr/local/libexec/yac-speakup-settings "", /usr/local/libexec/yac-pi-wifi "", /usr/bin/systemctl poweroff\n' "$account" > "$policy"
# Use the normal source installer, including its installation/shortcut offers.
python3 install_yac.py --pi
# A cancelled or incomplete source update must not continue with helper installation.
python3 - "$HOME/.local/yac" <<'PY'
from pathlib import Path
import sys
installed = Path(sys.argv[1])
for name in ('yac.py', 'modules/access_control.py', 'modules/wifi_control.py'):
    target = installed / name
    if not target.is_file() or target.read_bytes() != Path(name).read_bytes():
        raise SystemExit('Source installation was cancelled or incomplete. Rerun sh install.sh when ready.')
PY
echo 'Installing Pi support...'
sudo -v
sudo /usr/sbin/visudo -cf "$policy" >/dev/null
mkdir -p "$HOME/.local/bin" "$HOME/.config/yac"
install -m 755 pi-launcher.py "$HOME/.local/bin/yac-pi"
install -m 644 pi_audio.py "$HOME/.local/bin/pi_audio.py"
if [ ! -e "$HOME/.config/yac/pi-launcher.ini" ]; then
    install -m 644 pi/doc/pi-launcher.ini.example "$HOME/.config/yac/pi-launcher.ini"
fi
sudo install -d -m 755 /usr/local/libexec
sudo install -m 755 pi/audio-settings.py /usr/local/libexec/yac-pi-audio
sudo install -m 755 pi/speakup-settings.py /usr/local/libexec/yac-speakup-settings
sudo install -m 755 pi/wifi-settings.py /usr/local/libexec/yac-pi-wifi
sudo install -m 644 pi/yac-speakup-restore.service /etc/systemd/system/yac-speakup-restore.service
sudo install -m 440 "$policy" /etc/sudoers.d/yac-pi-complete
sudo /usr/sbin/visudo -c >/dev/null
sudo systemctl daemon-reload
sudo systemctl --quiet enable --now yac-speakup-restore.service
# Read-only checks: no connection changes and no private password entry.
printf '%s\n' '{"action":"status"}' | sudo -n /usr/local/libexec/yac-pi-wifi | python3 -c 'import json,sys; r=json.load(sys.stdin); sys.exit(0 if r.get("ok") else "Wi-Fi helper check failed: " + r.get("error", "unknown"))'
sudo systemctl is-enabled --quiet yac-speakup-restore.service
echo 'Installation Complete'
echo 'Type yac-pi to start.'
