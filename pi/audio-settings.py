#!/usr/bin/python3 -I
"""Fixed-purpose ALSA helper for the Pi image. SPDX-License-Identifier: GPL-3.0-only."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ALSA = Path('/etc/asound.conf')
MARK = '# Managed by YAC Pi audio selection\n'
SILENT = Path('/sys/accessibility/speakup/silent')


def run(args, check=True):
    return subprocess.run(args, capture_output=True, text=True, timeout=15, check=check)


def validate(request, base=Path('/proc/asound')):
    if not isinstance(request, dict):
        raise ValueError('Expected an audio request.')
    action = request.get('action')
    if action in ('begin', 'end', 'ready', 'ready-braille', 'complete') and set(request) == {'action'}:
        return action, None, None, None
    if action not in ('probe', 'apply') or set(request) != {'action', 'card', 'device', 'volume'}:
        raise ValueError('Unknown audio request.')
    card, device, volume = (request[key] for key in ('card', 'device', 'volume'))
    if (not isinstance(card, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', card)
            or type(device) is not int or not 0 <= device <= 255
            or type(volume) is not int or not 1 <= volume <= 100):
        raise ValueError('Invalid audio device or volume.')
    for directory in base.glob('card[0-9]*'):
        if (directory / 'id').read_text().strip() == card and (directory / f'pcm{device}p').is_dir():
            return action, card, device, volume
    raise ValueError('Selected playback device is no longer connected.')


def mixer(card, volume):
    controls = run(['/usr/bin/amixer', '-c', card, 'scontrols'], check=False)
    for control in re.findall(r"Simple mixer control '([^'\n]+)',(\d+)", controls.stdout):
        name = ','.join(control)
        details = run(['/usr/bin/amixer', '-c', card, 'sget', name], check=False)
        caps = re.search(r'Capabilities:([^\n]+)', details.stdout)
        if caps and 'pvolume' in caps.group(1).split():
            run(['/usr/bin/amixer', '-c', card, 'sset', name, f'{volume}%', 'unmute'], check=False)


def configuration(card, device):
    # Explicit type replacement is needed: ALSA's built-in defaults are integers.
    return (MARK + f'defaults.pcm.!card "{card}"\ndefaults.ctl.!card "{card}"\n'
            f'defaults.pcm.device {device}\n')


def replace(data):
    with tempfile.NamedTemporaryFile(dir=ALSA.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
            os.fchmod(stream.fileno(), 0o644)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        os.replace(temporary, ALSA)
    finally:
        temporary.unlink(missing_ok=True)


def apply(card, device):
    if ALSA.is_symlink():
        raise ValueError('Refusing to replace a linked ALSA configuration.')
    old = ALSA.read_bytes() if ALSA.exists() else None
    if old is not None and not old.startswith(MARK.encode()):
        raise ValueError('Existing /etc/asound.conf is not managed by YAC; review it manually.')
    data = configuration(card, device).encode()
    if old == data:
        run(['/usr/bin/systemctl', 'start', 'espeakup.service'])
        return
    try:
        replace(data)
        run(['/usr/bin/systemctl', 'restart', 'espeakup.service'])
    except BaseException:
        if old is None:
            ALSA.unlink(missing_ok=True)
        else:
            replace(old)
        run(['/usr/bin/systemctl', 'restart', 'espeakup.service'], check=False)
        raise


def finish_boot(action):
    if action != 'complete':
        SILENT.write_text('7\n' if action == 'ready-braille' else '6\n')
    # Keep the independent recovery armed until speech/audio setup succeeds.
    # Braille-only explicitly requests silence, so it cancels recovery here.
    if action in ('ready-braille', 'complete'):
        run(['/usr/bin/systemctl', 'stop', 'yac-boot-speech-recovery.timer'], check=False)


def main():
    import fcntl
    if sys.platform != 'linux' or os.geteuid() != 0 or len(sys.argv) != 1:
        raise ValueError('This helper requires Linux, root, and no arguments.')
    with open('/run/yac-pi-audio.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        request = json.loads(sys.stdin.read(4096))
        action, card, device, volume = validate(request)
        if action in ('ready', 'ready-braille', 'complete'):
            finish_boot(action)
        elif action == 'begin':
            run(['/usr/bin/systemctl', 'stop', 'espeakup.service'])
        elif action == 'end':
            run(['/usr/bin/systemctl', 'start', 'espeakup.service'])
        else:
            mixer(card, volume)
            if action == 'apply':
                apply(card, device)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(f'Pi audio: {error}', file=sys.stderr)
        sys.exit(1)
