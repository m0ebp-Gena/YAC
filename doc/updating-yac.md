# Updating YAC

Normal YAC radio control does not require an internet connection. The updater
contacts GitHub only when requested; it does not check for updates at startup.
If an update check fails, the message remains available until Enter returns
to YAC. The currently installed version stays usable offline.

Press `s`, then `u`, to open Update YAC on Windows, Linux or macOS.
Space closes the radio connection and opens the updater; `q` returns to Settings.
The updater checks published GitHub releases. It offers `r` to read changes,
`q` to cancel, and Space to download and install. No Git installation is needed.
The updater's prompts and release notes are currently English; the Settings
handover prompt is translated into YAC's supported languages.

## Linux, macOS and the Pi image

Use the installed source version: `~/.local/yac` on Linux or `~/Applications/yac`
on macOS. The existing `update-yac` command remains available outside YAC.
The updater downloads the source ZIP and its SHA-256 checksum, checks the
archive and runs the source installer. Personal settings, logs and the Python
environment are preserved. It restores program files if the installer fails.
Another running YAC prevents installation.

After a successful update or cancellation, YAC restarts in a fresh process.
After a failed update, read the error and press Enter to return to YAC.
On the Pi it retains the launcher's image environment and audio selection.
The ordinary source updater does not replace Pi launcher files or boot setup;
those belong to the separate Pi image-builder kit.

An extracted source tree outside the supported install location reports that
the updater is unavailable. Install it with the source installer first.

## Portable Windows version

The portable executable downloads the Windows ZIP and its matching checksum.
It does not install Python or run the source installer. Once verified, the
update opens an interactive Windows PowerShell console and closes YAC. The
installer waits for the original executable to exit before replacing program
files. Another YAC instance prevents replacement.

Settings in `yac.ini` and unrelated personal files/logs remain in place. Program
files are backed up during replacement; failed installation attempts restore
them. Recovery files are retained if installation fails. After success, press
Enter in the updater console to start the new executable. A cancelled check or
an up-to-date installation returns to YAC without installing anything.

The first Windows version providing this menu must be downloaded and extracted
normally. Existing older executables cannot gain this command until replaced.
Source-only Windows launches do not provide the portable Windows update path.

## Release requirements

Updates use published release assets and matching checksum files from the YAC
repository. They cannot install unpublished local beta work. A missing or
ambiguous package/checksum is reported; no installation is attempted. The
checksum detects a corrupted download; it is not a separate publisher signature.
Updates do not request administrator access or upgrade the operating system.
