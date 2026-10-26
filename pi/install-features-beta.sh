#!/bin/sh
# Existing Pi image: install s u/s w/s b/s o together; keep boot/audio/INI.
set -eu
cd "$(dirname "$0")/.."
echo 'Installing the Pi features beta. Quit YAC before continuing.'
sh pi/update-source-beta.sh
echo 'Updating speech, mode and audio helpers...'
sudo install -m 755 pi/speakup-settings.py /usr/local/libexec/yac-speakup-settings
sudo install -m 755 pi/audio-settings.py /usr/local/libexec/yac-pi-audio
if [ -f "$HOME/.local/bin/yac-pi" ]; then
    cp -p "$HOME/.local/bin/yac-pi" "$HOME/.local/bin/yac-pi.before-features-beta"
fi
install -m 644 pi_audio.py "$HOME/.local/bin/pi_audio.py"
install -m 755 pi-launcher.py "$HOME/.local/bin/yac-pi"
echo 'Installing the Wi-Fi helper and image cleanup command...'
sh pi/install-wifi.sh
echo 'Pi features beta installation complete.'
echo 's u Update; s w Wi-Fi; s b Access mode; s o Speech options.'
echo 'Your preferences, audio selection, launcher INI and boot setup were preserved.'
echo 'No reboot is needed. Start YAC with your usual Pi launcher.'
