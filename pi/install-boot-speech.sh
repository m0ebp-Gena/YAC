#!/bin/sh
# Update the existing Pi audio beta; do not reinstall YAC or change its INI.
set -eu
cd "$(dirname "$0")/.."
if [ "$(id -u)" = 0 ]; then
    echo 'Run as your normal login user, without sudo before this script.'
    exit 1
fi
test -f "$HOME/.local/bin/yac-pi"
test -f /etc/sudoers.d/yac-pi-beta
echo 'Updating the launcher and audio helper...'
cp -p "$HOME/.local/bin/yac-pi" "$HOME/.local/bin/yac-pi.before-boot-mute"
install -m 644 pi_audio.py "$HOME/.local/bin/pi_audio.py"
install -m 755 pi-launcher.py "$HOME/.local/bin/yac-pi"
sudo install -m 755 pi/audio-settings.py /usr/local/libexec/yac-pi-audio
sudo install -m 755 pi/boot-speech.py /usr/local/libexec/yac-boot-speech
sudo install -d -m 755 /etc/systemd/system/espeakup.service.d
sudo install -m 644 pi/yac-boot-speech.conf /etc/systemd/system/espeakup.service.d/yac-boot-speech.conf
sudo install -m 644 pi/yac-boot-speech-recovery.service /etc/systemd/system/yac-boot-speech-recovery.service
sudo install -m 644 pi/yac-boot-speech-recovery.timer /etc/systemd/system/yac-boot-speech-recovery.timer
sudo systemctl daemon-reload
sudo /usr/local/libexec/yac-boot-speech arm
# Enable for the NEXT boot; starting this timer now might invoke recovery
# immediately on a machine already up for more than two minutes.
sudo systemctl enable yac-boot-speech-recovery.timer
echo 'Boot speech mute installed. Saved audio and INI have been preserved.'
echo 'Reboot when ready. No initramfs rebuild is needed for this change.'
