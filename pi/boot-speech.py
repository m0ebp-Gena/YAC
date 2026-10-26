#!/usr/bin/python3 -I
"""Mute boot speech once, with an independent recovery path. GPL-3.0-only."""
import os
from pathlib import Path
import subprocess
import sys

SILENT = Path('/sys/accessibility/speakup/silent')
MARKER = Path('/run/yac-boot-speech-muted')


def mute():
    if MARKER.exists():
        return
    subprocess.run(['/usr/sbin/modprobe', 'speakup_soft'], check=True, timeout=15)
    SILENT.write_text('7\n')  # Flush pending speech and keep output muted.
    MARKER.touch(mode=0o600)


def recover():
    # Clear both mute bits and flush old boot text before restoring the backend.
    # A wedged service must not prevent the mute state from being cleared.
    if SILENT.exists():
        SILENT.write_text('6\n')
    subprocess.run(['/usr/bin/systemctl', 'start', 'espeakup.service'], check=True, timeout=20)
    SILENT.write_text('6\n')
    print('YAC boot speech recovery: console speech restored.', flush=True)


if __name__ == '__main__':
    if os.geteuid() != 0 or len(sys.argv) != 2 or sys.argv[1] not in ('mute', 'recover', 'arm'):
        sys.exit('Expected root invocation with mute, recover or arm.')
    try:
        if sys.argv[1] == 'arm':
            MARKER.touch(mode=0o600)
        else:
            (mute if sys.argv[1] == 'mute' else recover)()
    except Exception as error:
        sys.exit(f'YAC boot speech: {error}')
