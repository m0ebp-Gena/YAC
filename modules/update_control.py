"""Settings-to-updater handover. SPDX-License-Identifier: GPL-3.0-only."""
from pathlib import Path
import os
import subprocess
import sys

from modules import chat_int

REQUEST = 75


def supported(root):
    if sys.platform == 'win32':
        return bool(getattr(sys, 'frozen', False))
    if sys.platform in ('linux', 'darwin'):
        expected = Path.home() / ('Applications' if sys.platform == 'darwin' else '.local') / 'yac'
        return root.resolve() == expected.resolve() and (root / 'update_yac.py').is_file()
    return False


def confirm(root, language, read_key):
    if not supported(root):
        chat_int.show_response(chat_int.label(root, language, 'l327'))
        return False
    chat_int.show_response(chat_int.label(root, language, 'l326'))
    while True:
        key = read_key().casefold()
        if key == ' ':
            return True
        if key in ('q', '\x03', '\x04'):
            chat_int.show_done(root, language)
            return False


def run(root):
    """Called only after the radio closes and the application lock is released."""
    if sys.platform == 'win32':
        import update_yac
        result = update_yac.windows_main(root)
        if result == REQUEST:
            return 0  # The staged Windows installer must wait for this EXE to exit.
        if result:
            try:
                input('Press Enter to return to YAC.')
            except (EOFError, KeyboardInterrupt):
                return result
        os.execv(sys.executable, [sys.executable, *sys.argv[1:]])
    else:
        result = subprocess.run([sys.executable, str(root / 'update_yac.py')])
        if result.returncode:
            try:
                input('Update did not complete. Check the internet connection if needed. Press Enter to return to YAC.')
            except (EOFError, KeyboardInterrupt):
                return result.returncode
        # Load a fresh process: installed modules may have changed.
        os.execv(sys.executable, [sys.executable, str(root / 'yac.py'), *sys.argv[1:]])
    return 0
