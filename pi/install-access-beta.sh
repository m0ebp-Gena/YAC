#!/bin/sh
# Update s b/s o and their existing image helpers, preserving launcher INI.
set -eu
cd "$(dirname "$0")/.."
echo 'Updating speech and braille controls. Quit YAC first.'
sh pi/update-source-beta.sh
sudo install -m 755 pi/speakup-settings.py /usr/local/libexec/yac-speakup-settings
sudo install -m 755 pi/audio-settings.py /usr/local/libexec/yac-pi-audio
if [ -f "$HOME/.local/bin/yac-pi" ]; then
    cp -p "$HOME/.local/bin/yac-pi" "$HOME/.local/bin/yac-pi.before-access-beta"
fi
install -m 644 pi_audio.py "$HOME/.local/bin/pi_audio.py"
install -m 755 pi-launcher.py "$HOME/.local/bin/yac-pi"
echo 'Speech and braille controls updated. Launcher INI and boot setup preserved.'
echo 'Start YAC using the Pi launcher. No reboot is required for this update.'
