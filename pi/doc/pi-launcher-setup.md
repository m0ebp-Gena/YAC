# Raspberry Pi console launcher

For Raspberry Pi OS Lite based on Debian 13. Run the commands as the normal
account that will automatically log in, using sudo only where shown.

## Install and test YAC first

From the source folder copied to the Pi:

```sh
sudo apt install python3-venv alsa-utils
sh install-yac.sh
~/.local/yac/run-yac
```

The installer normally installs into `~/.local/yac`. Check language, name,
radio discovery and BRLTTY access before enabling automatic startup. Do not
copy a Windows `.venv` to the Pi; create the environment on the Pi.

## Install the Pi launcher

From that same source folder:

```sh
mkdir -p ~/.local/bin ~/.config/yac
install -m 755 pi-launcher.py ~/.local/bin/yac-pi
install -m 644 pi_audio.py ~/.local/bin/pi_audio.py
cp -n pi/doc/pi-launcher.ini.example ~/.config/yac/pi-launcher.ini
```

Edit `~/.config/yac/pi-launcher.ini` if necessary. If not using the source
installer, set `yac_command` to an executable shell script which changes to
your YAC folder and runs its Pi Python environment's `python yac.py`.

## Configure audio

The Pi audio beta adds first-run spoken output selection. Install its root
helper and permissions using `sh pi/install-pi-beta.sh` from the special beta
package. See [Pi audio beta setup](pi-audio-beta.md) for the current procedure.
The following card/control settings are optional overrides after selection.

Leave `alsa_control` empty to use existing audio settings. To make the launcher
set a level, identify and test the actual output first:

```sh
aplay -l
amixer scontrols
```

For a particular card use `amixer -c CARD scontrols`. Put that card's identifier
in `alsa_card` and the exact simple mixer control name in `alsa_control`.
For example, only if your device lists a `PCM` control:

```ini
alsa_card = default
alsa_control = PCM
volume = 70
```

The launcher attempts to set and unmute that control before starting YAC.
It continues if this fails. Some outputs have no software volume control;
70% is not a guarantee of an audible or appropriate speaker level. This does
not select HDMI/USB output, test speakers, or change BRLTTY's own volume.
After selecting and testing your desired ALSA settings, you can save them:

```sh
sudo alsactl store
```

ALSA state restoration at boot and the launcher's explicit volume setting are
separate: a configured launcher volume overrides the restored level on launch.
Set `access_mode = braille` to bypass launcher audio changes. This setting does
not yet switch BRLTTY speech on/off; use BRLTTY preferences for that.

## Allow confirmed shutdown

First test whether your account already has permission:

```sh
sudo -n -l
command -v systemctl
```

If it does not already allow passwordless shutdown, use `sudo visudo -f
/etc/sudoers.d/yac-poweroff` and add the following as ONE line, replacing
`YOURUSER` with your real account name and using the verified systemctl path:

```text
YOURUSER ALL=(root) NOPASSWD: /usr/bin/systemctl poweroff
```

Do not grant the entire launcher passwordless root access. Test manually:

```sh
~/.local/bin/yac-pi
```

Currently, after a normal YAC exit, the launcher asks `Shut down the Pi? Y/N:`.
Type the letter and Enter. N returns to the shell. Y requests poweroff.
A YAC error or interruption returns to the shell without requesting shutdown.
This temporary English prompt will move into YAC's translated interface when
appliance mode is implemented.

## Enable console automatic login and startup

Run `sudo raspi-config`. Choose console/text boot and enable console automatic
login for this account (wording varies by release). The console boot target is
`multi-user.target`; a separate YAC system service is not required.

```sh
systemctl get-default
```

If necessary set the next boot's default explicitly:

```sh
sudo systemctl set-default multi-user.target
```

For the default Bash login shell, check which login file exists. Bash reads
the first available of `~/.bash_profile`, `~/.bash_login`, `~/.profile`.
Edit that active file; normally Raspberry Pi OS uses `~/.profile`. Append:

**START COPYING BELOW. Copy only the three shell lines, from `if` through `fi`.**
If reading the raw Markdown file, do not copy the opening three backticks and
`sh` language label, or the closing three backticks. Those mark formatting;
they are not commands to put in your profile.

```sh
if [ -z "${SSH_CONNECTION:-}" ] && [ "$(tty 2>/dev/null)" = /dev/tty1 ] && [ ! -e "$HOME/.config/yac/disable-autostart" ]; then
    python3 "$HOME/.local/bin/yac-pi"
fi
```

**STOP COPYING. The `fi` line above is the last line to copy.**
Do not copy these instructions or add a separate `sh` line or backticks.

Do not use `exec`: retaining the login shell provides recovery after a failure.
Do not add this to `.bashrc`, which would start it in ordinary subshells too.
Reboot once ready. BRLTTY should remain enabled and configured independently.

## Recovery and current limits

From SSH or another console, disable automatic YAC startup with:

```sh
touch ~/.config/yac/disable-autostart
```

Remove that file to reenable it. The same user's settings directory is needed.
You can also remove the login-file block. Keep SSH access available while testing.

Implemented here: console login entry point, optional ALSA startup level,
direct handover to current YAC, and confirmed shutdown after normal exit.
The updated YAC source adds `so` Speakup speech options through the image
helper; `sb` mode switching is reserved and not yet adapted to Speakup; see [Pi speech options and setup](pi-speech-options.md).
`ss` remains tuning step. The launcher sets the image-only environment flag.
Not implemented yet: five-minute inactivity timer, four-minute translated warning, `w` cancellation,
or appliance-mode exit protocol. In particular this launcher will NOT shut
down automatically after five minutes. Those require changes inside YAC so
actual command activity, translations and resource cleanup remain correct.

Before hosting an image, complete the mandatory image licensing/source review
recorded in TODO.md.

References: [Raspberry Pi configuration](https://www.raspberrypi.com/documentation/computers/configuration.html)
and [systemd targets](https://freedesktop.org/software/systemd/man/latest/systemd.html).
