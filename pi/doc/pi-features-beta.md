# Pi features beta — 22 October 2026

This ZIP combines the four new Settings controls for testing on your existing
Pi image. It includes all YAC source and Pi launcher/helper materials. Pi notes
remain separate under `pi/doc`; ordinary source and Windows packages exclude them.

## Install once

Quit YAC first. Copy `yac-pi-features-beta-2026-10-22.zip` to `/home/yac`.
In your Pi SSH session, run these two commands one at a time as user yac.

Start copying the next two lines:

```sh
unzip -o /home/yac/yac-pi-features-beta-2026-10-22.zip -d /home/yac/yac-pi-features-beta-2026-10-22
sh /home/yac/yac-pi-features-beta-2026-10-22/pi/install-features-beta.sh
```

End copying at the sh line above.

The installer uses the existing Python environment, checks the application
lock, updates YAC and installs the speech/audio/Wi-Fi helpers. It may ask for
your sudo password. It does not repeat apt package installation or edit your
boot configuration, .profile, saved audio output, launcher INI or personal
YAC preferences. No reboot is needed. If YAC is still running, close it first
and rerun the installer. Wait for “Pi features beta installation complete.”

## Start at the Pi local console

Start copying the next line:

```sh
python3 /home/yac/.local/bin/yac-pi
```

End copying at the python3 line above.

- `s o`: speech options. Rate is selected initially. `.` increases and `,`
  decreases. Every adjustment applies and saves immediately. `r` rate, `v`
  volume, `p` pitch, `u` punctuation, `t` test, `d` YAC defaults, `h` help,
  `q` back keeping changes. There is no separate save key.
- `s b`: access mode. `b` speech and braille, `r` braille only, `s` speech
  only, `h` help, `q` back. Each choice applies and saves immediately. Braille
  input/output remains available in every mode. In braille-only mode, use
  `s` or `b` within this menu to restore speech.
- `s w`: country, SSID and private password entry. Space confirms connection,
  `e` edits and `q` returns before connecting. Ctrl+C cancels an entry; typed
  letters and punctuation in fields are literal. It supports visible home
  networks. Connection does not prove internet access.
- `s u`: update. Space hands over after closing the radio. The updater offers
  `r` release notes, `q` cancel and Space install. It checks published releases,
  not this unpublished local ZIP. Without internet, read the error and press
  Enter to return to YAC. It does not update the operating system or Pi kit.

`s s` remains tuning step.

## Test checklist

Change a speech value then q; reopen to verify it stayed. Test access modes
and return to speech; reboot to check the saved mode and speech settings.
Try Wi-Fi with the correct country and your router's SSID/password; check
persistence after reboot and a failed-password/cancel path. Test the updater
without internet, then check release notes/cancel with internet. Do not expect
unpublished changes to be available through s u.

The user has already confirmed that their image starts with Ethernet unplugged
and no Wi-Fi configured. Automated tests pass; these latest menu/backend changes
still require hardware testing. Nothing has been pushed or published.

For publication cleanup later, use `sudo yac-image-clear-wifi` at the local
console, then type YES. See [Wi-Fi and cleanup](pi-wifi.md) for seed-file checks
and [speech controls](pi-speech-options.md) for details. Removing identity and
completing the image licence/source review remain separate release tasks.
