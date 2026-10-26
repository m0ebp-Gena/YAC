# Pi speech options with Speakup

YAC's `s o` menu now uses Speakup/espeakup. BRLTTY continues providing braille.
The previous BRLTTY speech helper is superseded: do not install or use it.
This is a local implementation awaiting testing on the Pi; nothing is pushed.

## Keys

Press `s`, then `o`:

- Repeat `o` to cycle Rate, Volume, Pitch and Punctuation, like repeating `o`
  in the offset controls. Rate is selected on entry.
- Rate and pitch range from 0 to 9; speech volume from 1 to 9, separately from
  ALSA volume. Punctuation choices are None, Some, Most and All.
- Full stop increases the selected setting; comma decreases it. Endpoints stop.
- Every adjustment applies immediately and saves for future boots. There is no
  separate Apply/Save key. Rate is selected when the menu opens, like the initial
  selection in the offset controls. The compact key list starts with h Help.
- `t`: display a speech test using the current settings.
- `d`: immediately apply and save YAC defaults: rate 2, volume 5, pitch 5,
  punctuation Some. Unrelated Speakup settings, braille and system volume are untouched.
- `q`: return to Settings, keeping changes.
- `h`: help.

`s s` remains tuning step. `s b` opens the saved access-mode choices:
`h` Help, repeat `b` to cycle speech and braille, braille only, speech only;
leave the wanted mode selected and press `q` to apply, save and return.
Browsing does not apply a mode until `q`. The applied mode is saved in the launcher INI for next boot.
Braille-only mutes Speakup without stopping BRLTTY or losing braille input/output.
The speech choices restore Speakup. An attached braille display remains available
even with speech-only selected; no display or keyboard is disabled.

For an existing beta, quit YAC, extract the refreshed special Pi ZIP, and run
`sh pi/install-access-beta.sh` from the extracted folder. It updates YAC and
the speech/audio helpers without repeating package installation or changing
boot setup. It preserves the launcher INI. No reboot is needed to try the menus.

## One-time image setup

Use a working SSH connection while setting up. YAC itself runs as your normal
user. The helper is a separate root-owned program with a fixed settings whitelist.
These steps assume the login account is `yac` and you are in the extracted Pi kit.
They do not replace your existing profile or change automatic login.

First confirm Speakup/espeakup works with YAC. Keep BRLTTY Autospeak off.
No BRLTTY speech settings are modified by this helper.

Install the helper and boot-restore service:

```sh
sudo install -d -o root -g root -m 755 /usr/local/libexec
sudo install -o root -g root -m 755 pi/speakup-settings.py /usr/local/libexec/yac-speakup-settings
sudo install -o root -g root -m 644 pi/yac-speakup-restore.service /etc/systemd/system/yac-speakup-restore.service
sudo systemctl daemon-reload
sudo systemctl enable yac-speakup-restore.service
```

The restore service runs after espeakup at boot. It restores only fields actually
saved through YAC, from `/var/lib/yac-speakup/settings.json`. With no saved file,
it does nothing. This does not save all Speakup settings or override choices YAC
has never saved. Do not combine it with another boot tool that restores different
values for the same fields.

Open the permission file:

```sh
sudo visudo -f /etc/sudoers.d/yac-speakup-settings
```

START COPYING BELOW. Copy only the single permission line, without formatting
backticks, language labels or these instructions.

```text
yac ALL=(root) NOPASSWD: /usr/local/libexec/yac-speakup-settings ""
```

STOP COPYING. The permission line above is the last line to copy.

If visudo uses nano, Ctrl+O then Enter saves, and Ctrl+X exits. Visudo checks
syntax. The empty quotes restrict sudo permission to calls without arguments.
Do not give passwordless sudo to the whole YAC application or Python interpreter.

Check the helper without changing anything:

```sh
printf '%s\n' '{"action":"status"}' | sudo -n /usr/local/libexec/yac-speakup-settings
```

It should report `ok: true`, `backend: speakup` and current speech preferences.
The active synth must be `soft`, and Speakup's sysfs files must be available.
The helper has no service restart, driver selection or arbitrary path interface.

Install the updated launcher as before, so it sets `YAC_PI_IMAGE=1` for YAC.
You also need the updated YAC source; the helper kit alone does not update YAC.
Normal source/Windows/macOS launches keep their external screen-reader settings.

## First test and limitations

Start with rate: `s o`, full stop once. Use `t` to test; `q` returns.
Repeat `o` to select Volume, then use full stop or comma to adjust it.
Check speech and braille remain available. Test saved values after reboot before
releasing the image. Automated tests use fake sysfs files, not actual Pi hardware.

Punctuation changes `/sys/accessibility/speakup/punc_level` only. Review punctuation
(`reading_punc`) is preserved. This requires `soft/direct` to be zero; if your
installation delegates punctuation to the synthesizer, the helper refuses the
punctuation change instead of silently changing that arrangement. Rate, pitch
and volume can still be changed. The kernel may expose punctuation values 3 and
4 as All; YAC writes 4 for its All choice.

If any write or readback fails, the helper attempts to restore the affected live
values. If saving fails, it also rolls back the live changes. Never make all of
`/sys/accessibility/speakup` writable merely to operate this menu.

The general five-minute startup activity timer and language/voice changes remain
separate tasks. Existing Morse cues are unchanged. Espeakup startup hangs are an
unresolved Pi release blocker; local tests do not establish working hardware speech.

References: [kernel Speakup controls](https://www.kernel.org/doc/html/latest/admin-guide/abi-stable.html),
[espeakup](https://github.com/linux-speakup/espeakup).
