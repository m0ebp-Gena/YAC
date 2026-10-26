# Pi Wi-Fi setup and image cleanup

`s w` opens Wi-Fi setup only when YAC is launched by the configured Pi launcher.
It does not change networking on Windows, macOS or ordinary source launches.
YAC startup and normal radio control remain usable without internet.

## Install this beta

The refreshed special Pi beta ZIP includes the updated YAC source, the Wi-Fi
module, its helper and the cleanup script. Quit YAC, extract into the existing
beta folder with `unzip -o`, then run `sh pi/install-wifi-beta.sh` from that
folder. This short installer updates an existing YAC and installs the Wi-Fi
helper without repeating package installation or changing boot/audio setup.
It preserves YAC preferences and launcher settings. Use the full
`sh pi/install-pi-beta.sh` installer only for a fresh image.
No individual Python files or service files need copying by hand.

If YAC is already updated separately, `sh pi/install-wifi.sh` installs only the
new helper, its narrow sudo permission and the image-builder cleanup command.
Use the normal user account for these installers, not sudo before the script.

## Use s w

1. Enter the two-letter country code where the Pi will operate. Examples:
   GB for the United Kingdom, DE for Germany, ES for Spain, PL for Poland.
   UK is also accepted and converted to GB. Blank Enter keeps an existing code.
2. Enter the router's network name (SSID) exactly, including case and spaces.
3. Enter the password and press Enter. For an open network, leave it blank.
4. Review the country and network name. Space connects and saves, e edits,
   q returns without connecting. The password is not included in the review.

During entry, punctuation and letters such as q are literal characters.
Ctrl+C cancels an entry. Backspace uses the terminal's usual line editing.
Password entry hides text and temporarily disables Speakup key echo; the
previous key echo setting is restored on submission, cancellation or error.
Screen-reader speech remains available for the rest of setup. If a process
is forcibly killed during password entry, reboot restores normal boot settings;
no password is shown in the transcript.

The helper receives credentials through stdin, not shell commands or process
arguments. NetworkManager stores the connection in a root-only keyfile in
`/etc/NetworkManager/system-connections`. Credentials are not saved in YAC's INI
or logs. YAC-created profiles have names beginning `YAC Wi-Fi` and filenames
beginning `yac-wifi-`. A failed connection removes the new attempt's profile
and attempts to reactivate the previous Wi-Fi connection. Existing saved
networks are retained. The selected country remains set after a connection
failure because it is the country the user specified for this hardware.

This initial version uses the first detected Wi-Fi adapter and visible home
networks: WPA/WPA2 Personal, WPA3 Personal and open networks. Hidden SSIDs,
enterprise/802.1X, WEP and OWE networks require the system tools. Connection
can take up to two minutes. “Connected” confirms the Wi-Fi connection, not
internet access; s u checks internet separately. Changing Wi-Fi over an SSH
session using that interface can disconnect the session; use the local console.

## Clear Wi-Fi before publishing the image

At the local Pi console, run this single command. It asks you to type YES
before making changes. Do not run it as part of ordinary user setup.

Start copying the next line:

```sh
sudo /usr/local/sbin/yac-image-clear-wifi
```

End copying at the command above.

It removes ALL saved NetworkManager Wi-Fi profiles, including connections
created outside YAC, disables Wi-Fi, and clears the saved WLAN country so the
next user can configure their own. Ethernet profiles are preserved. If boot
seed files appear to contain Wi-Fi configuration, the script names them for
review without printing their contents. Those seed files could recreate a
connection and are not silently edited. Cleanup reports incomplete status
when such review remains.

This command cleans Wi-Fi configuration. Personal identity, SSH keys, history,
logs, audio preferences and licensing/source checks are separate image-release
tasks. Do not configure personal Wi-Fi again after cleanup before capturing
the image. Check offline boot and s w country/connection setup on a fresh copy.

## Verification status

Local automated tests cover cancellation, literal password characters, platform
boundaries, country/input validation, key echo restoration, profile encoding,
failed-connection rollback and cleanup's Wi-Fi-only profile selection. Real
Pi Wi-Fi setup, persistence after reboot and publication cleanup need hardware
testing before release.
