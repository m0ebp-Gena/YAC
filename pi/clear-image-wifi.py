#!/usr/bin/python3 -I
"""Image-builder Wi-Fi cleanup. Run at the local Pi console. GPL-3.0-only."""
import os
from pathlib import Path
import re
import subprocess
import sys


def profiles():
    result = subprocess.run(['/usr/bin/nmcli', '-t', '-f', 'UUID,TYPE', 'connection', 'show'],
                            capture_output=True, text=True, timeout=15, check=True)
    return [row.split(':', 1)[0] for row in result.stdout.splitlines()
            if row.endswith((':802-11-wireless', ':wifi')) and
            re.fullmatch('[0-9a-fA-F-]{36}', row.split(':', 1)[0])]


def seed_warnings():
    # Do not print seed contents: they can contain passwords, users and SSH keys.
    return [path for path in (Path('/boot/firmware/network-config'), Path('/boot/firmware/user-data'))
            if path.is_file() and re.search(r'(?i)\bwifi\b|wifis|wireless|access-points|ssid|psk|wpa_supplicant|\.nmconnection',
                                           path.read_text(errors='replace'))]


def main():
    if sys.platform != 'linux' or os.geteuid() != 0:
        print('Run with sudo at the Pi local console, just before preparing the image.')
        return 1
    if os.environ.get('SSH_CONNECTION') or not sys.stdin.isatty():
        print('Use the local Pi console. Removing Wi-Fi can disconnect SSH.')
        return 1
    pending = profiles()
    print(f'This removes ALL {len(pending)} saved NetworkManager Wi-Fi profiles, including profiles made outside YAC.')
    print('It also disables Wi-Fi and clears the saved WLAN country for first-user setup.')
    if input('Prepare image Wi-Fi cleanup? Type YES: ').strip() != 'YES':
        print('Cancelled. Nothing changed.')
        return 0
    for identifier in pending:
        subprocess.run(['/usr/bin/nmcli', 'connection', 'delete', 'uuid', identifier],
                       capture_output=True, timeout=15, check=True)
    subprocess.run(['/usr/bin/nmcli', 'radio', 'wifi', 'off'], capture_output=True, timeout=15, check=True)
    cmdline = Path('/boot/firmware/cmdline.txt')
    words = [word for word in cmdline.read_text().split() if not word.startswith('cfg80211.ieee80211_regdom=')]
    cmdline.write_text(' '.join(words) + '\n')
    subprocess.run(['/usr/sbin/iw', 'reg', 'set', '00'], capture_output=True, timeout=10, check=False)
    warnings = seed_warnings()
    if profiles():
        print('Wi-Fi cleanup incomplete: saved profiles remain.')
        return 1
    print('NetworkManager Wi-Fi profiles removed. WLAN country cleared.')
    for path in warnings:
        print(f'Review {path}: Wi-Fi seed settings may recreate credentials. Contents have not been printed or changed.')
    print('Also clear personal history/logs and complete the separate identity/licensing image checklist.')
    print('Country state is fully reset on the next boot. Do not configure Wi-Fi again before capturing the image.')
    return 1 if warnings else 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, subprocess.SubprocessError):
        print('Image Wi-Fi cleanup did not complete. Check the remaining profiles at the local console.')
        sys.exit(1)
    except (EOFError, KeyboardInterrupt):
        print('\nCancelled.')
        sys.exit(1)
