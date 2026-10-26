# Pi audio selection beta — start here

## Internet access is optional

The new [Pi Wi-Fi setup](pi-wifi.md) provides `s w` inside YAC. Its installer
also supplies the one-command image-builder Wi-Fi cleanup tool.

The ready-made image must support normal radio operation without internet.
Audio selection and YAC startup do not perform network checks. The updater
needs internet only when the user requests s u. Ethernet is the simplest
connection: attach a cable to a router with internet access. For Wi-Fi, run
`sudo raspi-config` and use System Options, Wireless LAN, to enter the network
name and password. Network credentials are personal and must be removed before
redistributing an image. Package/source installation also needs access to its
dependencies; that is separate from using a prepared image offline.

Image-builder acceptance test: boot with Ethernet disconnected and no configured
Wi-Fi. Confirm that Morse, Speakup, braille and radio operation still start.
OS services may affect boot time; do not require a network connection to start YAC.

This special package contains YAC source and the Pi launcher materials.
Pi instructions stay in `pi/doc`; ordinary source and Windows packages do
not include them. This beta needs testing on the Pi; it is not a published
release. It does not change Windows or Mac startup.

## Install on your existing Pi

Copy the ZIP to `/home/yac`. In the Pi SSH session, run these commands one at
a time. Copy only the command lines between the copy instructions.

Start copying the next three lines:

```sh
unzip yac-pi-audio-beta-2026-10-22.zip -d /home/yac/yac-pi-audio-beta-2026-10-22
cd /home/yac/yac-pi-audio-beta-2026-10-22
sh pi/install-pi-beta.sh
```

End copying at the sh line above.

Answer Y when the source installer asks to update YAC. The installer uses
sudo for system files; it may ask for your password. Run the script as yac,
not with sudo before the script name. It preserves YAC preferences and the
launcher INI, with a backup of the previous launcher and INI.

The installer puts all files in place. You do not need to copy Python files
manually or change your working `.profile`. It does not enable auto-login
or edit boot configuration. Keep your existing auto-login setup.
Plymouth was tested and rejected: Speakup repeatedly announced black squares
and then login text. Disable its splash; it is not a Speakup boot mute.
In the Pi SSH session run the following lines one at a time. The second line
restores quiet kernel logging because raspi-config removes quiet with splash.

Start copying the next three lines:

```sh
sudo raspi-config nonint do_boot_splash 1
sudo sed -i 's/$/ quiet/' /boot/firmware/cmdline.txt
sudo reboot
```

End copying at the reboot line above.

After disabling the splash, remove its packages with `sudo apt purge plymouth
rpd-plym-splash plymouth-themes plymouth-label libplymouth5`. Then use
`sudo apt autoremove --purge` to remove unused dependencies. Review that
second removal list because it may include unrelated packages already unused.
Finally run `sudo update-initramfs -u` and reboot. The saved YAC audio output
is separate from these packages. Boot speech suppression and login chatter
remain separate work to be tested.

## Boot speech mute update

The updated beta includes `pi/install-boot-speech.sh`. After copying and
extracting the refreshed ZIP, run this script as your normal user. It updates
only launcher/helper files and boot speech configuration; it does not reinstall
YAC or packages, edit the INI, or change .profile.

Start copying the next line:

```sh
sh /home/yac/yac-pi-audio-beta-2026-10-22/pi/install-boot-speech.sh
```

End copying at the sh line above. Reboot when it reports completion.

A systemd espeakup drop-in mutes Speakup once per boot, before the speech
backend starts. The launcher unmutes before audio selection and before YAC,
so the audio confirmation and saved-output feedback remain spoken. Later
espeakup restarts do not mute again. Morse output is independent and remains
audible. This does not suppress boot text on the braille display.

An independent timer restores console speech two minutes after boot if the
launcher has not completed the handover. The launcher cancels that timer once
it restores speech. Invalid configuration or missing YAC also restores speech
before reporting the error. Braille-only startup cancels recovery without
unmuting Speakup. The s b menu now saves and applies that startup mode.

No kernel command-line change or initramfs rebuild is needed for this mute.
To undo it, remove `/etc/systemd/system/espeakup.service.d/yac-boot-speech.conf`,
disable `yac-boot-speech-recovery.timer`, reload systemd and reboot. The audio
selection helper can remain installed. These new boot changes require Pi testing.
It preserves your existing Morse files and boot cue service. It supplies
missing DE, K and 73 text files, and includes an optional service template
under `pi` for future image builds. Before the first audio selection, the
early DE cue may still fail because the default output has not yet been set.

## Test at the Pi console

Quit any YAC already running and return to the Pi's local console. Test there
so Enter comes from the keyboard or braille display attached to that console.

Start copying the next line:

```sh
python3 /home/yac/.local/bin/yac-pi
```

End copying at the python3 line above.

The launcher cycles through ALSA playback outputs. Each speaks, in English,
“Audio setup. Press Enter if you can hear this.” Press Enter while hearing
the prompt or during the following eight seconds. The chosen output is saved
in `/home/yac/.config/yac/pi-launcher.ini`. YAC then follows its existing
language/name/radio startup. If language and name are already saved, they
are not asked again.

The test uses eSpeak NG directly, not Speakup or the existing default device.
Speakup's backend is stopped during testing and restarted afterwards.
The helper selects a system ALSA default for both Speakup and Morse. The
selection changes the default ALSA capture card too; radio/decoder inputs
should be selected explicitly in their existing YAC audio settings.

## Later boots and changing speakers

A connected saved device skips the test. Selection is repeated if it is
missing. The device is stored by its ALSA identifier and playback device
number, not its changing card number. Similar identical USB units can still
have unstable ALSA identifiers; multiple identical speakers need hardware
testing. A connected but switched-off speaker cannot be detected.

To choose again deliberately, at the local console use:

Start copying the next line:

```sh
python3 /home/yac/.local/bin/yac-pi --audio-setup
```

End copying at the python3 line above.

There is no new YAC key binding for audio selection in this beta.

## Volume, braille-only mode and no response

The launcher tries the INI volume (70 percent by default) on playback mixer
controls before each output test. Hardware without an adjustable playback
volume is left alone. Physical volume controls may still need adjusting.
After confirmation, the existing optional alsa_card/alsa_control overrides
should be left blank/default unless deliberately configured for that output.

`access_mode = braille` bypasses audio selection/preparation and mutes Speakup
at launcher startup. YAC's s b menu changes and saves the mode immediately.
It leaves the speech backend running so s o settings remain available, and
never disables an attached braille display or its input.

Without Enter confirmation, selection continues for five minutes. Prompts
during the last minute explain the approaching shutdown. At timeout the
launcher restores the speech backend and requests safe poweroff. This timer
is only for unconfirmed audio setup; it does not interrupt normal radio use.
Ctrl+C cancels setup, restores the backend and returns to the console.

## Installed files and recovery

- Launcher: `/home/yac/.local/bin/yac-pi`.
- Audio module: `/home/yac/.local/bin/pi_audio.py`.
- Root audio helper: `/usr/local/libexec/yac-pi-audio`.
- Settings: `/home/yac/.config/yac/pi-launcher.ini`.
- Shared ALSA selection: `/etc/asound.conf`, marked as managed by YAC.
- Narrow sudo permissions: `/etc/sudoers.d/yac-pi-beta`.
- Speakup options helper and restore service are also included for YAC's so menu.

The audio helper refuses to overwrite an existing, unmanaged `/etc/asound.conf`.
Per-user `.asoundrc` files can override the system default; review those manually
if present. This beta does not remove them. Your diagnostic report showed neither.

If setup fails, copy the error from SSH or save a diagnostic report. The launcher
returns to the console rather than saving an unconfirmed choice. A failed Speakup
restart rolls back the ALSA configuration. The original launcher is saved as
`/home/yac/.local/bin/yac-pi.before-audio-beta`.

Before sharing the image, reset audio_setup_complete to no, clear audio_card
and audio_device in the INI, and remove the YAC-managed `/etc/asound.conf`.
Also complete the image licence/source review and remove personal preferences.
Do not distribute a hardware-tested claim until this beta passes your tests.
