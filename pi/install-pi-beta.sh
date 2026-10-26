#!/bin/sh
# Install the special Pi beta as the normal console login user.
set -eu
cd "$(dirname "$0")/.."
if [ "$(id -u)" = 0 ]; then
    echo 'Run this script as the normal YAC user, without sudo.'
    exit 1
fi
sudo apt-get install python3-venv alsa-utils espeak-ng espeakup cw
sh install-yac.sh
mkdir -p "$HOME/.local/bin" "$HOME/.config/yac"
if [ -f "$HOME/.local/bin/yac-pi" ]; then
    cp -p "$HOME/.local/bin/yac-pi" "$HOME/.local/bin/yac-pi.before-audio-beta"
fi
if [ -f "$HOME/.config/yac/pi-launcher.ini" ]; then
    cp -p "$HOME/.config/yac/pi-launcher.ini" "$HOME/.config/yac/pi-launcher.ini.before-audio-beta"
else
    cp pi/doc/pi-launcher.ini.example "$HOME/.config/yac/pi-launcher.ini"
fi
install -m 644 pi_audio.py "$HOME/.local/bin/pi_audio.py"
install -m 755 pi-launcher.py "$HOME/.local/bin/yac-pi"
mkdir -p "$HOME/.local/share/cw"
for cue in de k 73; do
    if [ ! -e "$HOME/.local/share/cw/$cue" ]; then
        install -m 644 "pi/cw/$cue" "$HOME/.local/share/cw/$cue"
    fi
done
sudo install -d -m 755 /usr/local/libexec
sudo install -m 755 pi/audio-settings.py /usr/local/libexec/yac-pi-audio
sudo install -m 755 pi/speakup-settings.py /usr/local/libexec/yac-speakup-settings
sudo install -m 644 pi/yac-speakup-restore.service /etc/systemd/system/yac-speakup-restore.service
account=$(id -un)
case "$account" in
    *[!a-zA-Z0-9_-]*|'') echo 'Account name needs manual sudoers configuration.'; exit 1 ;;
esac
policy=$(mktemp)
trap 'rm -f "$policy"' EXIT HUP INT TERM
printf '%s ALL=(root) NOPASSWD: /usr/local/libexec/yac-pi-audio "", /usr/local/libexec/yac-speakup-settings "", /usr/bin/systemctl poweroff\n' "$account" > "$policy"
sudo /usr/sbin/visudo -cf "$policy"
sudo install -m 440 "$policy" /etc/sudoers.d/yac-pi-beta
sudo systemctl daemon-reload
sudo systemctl enable yac-speakup-restore.service
sh pi/install-boot-speech.sh
sh pi/install-wifi.sh
echo 'Pi beta installed. Existing INI and login startup have been preserved.'
echo 'Test from the Pi console: python3 /home/'"$account"'/.local/bin/yac-pi'
