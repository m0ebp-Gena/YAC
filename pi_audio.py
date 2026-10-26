"""First-run audio selection for the Pi image. SPDX-License-Identifier: GPL-3.0-only."""
import configparser
import json
import os
from pathlib import Path
import re
import select
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass

HELPER = '/usr/local/libexec/yac-pi-audio'


@dataclass(frozen=True)
class Output:
    card: str
    device: int
    name: str


def outputs(base=Path('/proc/asound')):
    """Use ALSA identifiers, never a saved card number; include every playback PCM."""
    found = []
    for card in sorted(base.glob('card[0-9]*')):
        try:
            identifier = (card / 'id').read_text().strip()
            if not re.fullmatch(r'[A-Za-z0-9_-]+', identifier):
                continue
            for pcm in sorted(card.glob('pcm*p')):
                match = re.fullmatch(r'pcm(\d+)p', pcm.name)
                if match:
                    found.append(Output(identifier, int(match[1]), identifier))
        except OSError:
            continue
    return found


def helper(action, **values):
    result = subprocess.run(['sudo', '-n', HELPER],
                            input=json.dumps(dict(action=action, **values)),
                            capture_output=True, text=True, timeout=25)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or
                           'Pi audio helper failed; check its installation and sudo permission.')


def save(config, path, output):
    if not config.has_section('launcher'):
        config.add_section('launcher')
    config['launcher'].update(audio_setup_complete='yes', audio_card=output.card,
                              audio_device=str(output.device))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         delete=False) as stream:
            temporary = Path(stream.name)
            config.write(stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def enter(timeout):
    ready, _, _ = select.select([sys.stdin], [], [], max(0, timeout))
    if not ready:
        return False
    line = sys.stdin.readline()
    if not line:
        raise EOFError('Audio setup needs an interactive console.')
    return line in ('\n', '\r\n')


def prompt(output, words, deadline, confirm=True):
    """Listen while speech plays and afterwards; stop playback on confirmation."""
    import termios
    termios.tcflush(sys.stdin.fileno(), termios.TCIFLUSH)
    with tempfile.TemporaryDirectory(prefix='yac-audio-') as directory:
        wave = Path(directory) / 'prompt.wav'
        with wave.open('wb') as stream:
            subprocess.run(['/usr/bin/espeak-ng', '-v', 'en', '-s', '155', '--stdout', words],
                           stdout=stream, stderr=subprocess.PIPE, check=True,
                           timeout=max(0.1, min(10, deadline - time.monotonic())))
        player = subprocess.Popen(['/usr/bin/aplay', '-q', '-D',
                                   f'plughw:CARD={output.card},DEV={output.device}', str(wave)],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            # A failed/unplugged output cannot hold up cycling or the overall timer.
            end = min(deadline, time.monotonic() + 25)
            finished = None
            while time.monotonic() < end:
                status = player.poll()
                if status is not None:
                    if status:
                        return False
                    if not confirm:
                        return False
                    if finished is None:
                        finished = time.monotonic() + 8
                    if time.monotonic() >= finished:
                        return False
                if confirm and enter(min(0.1, max(0, end - time.monotonic()))):
                    return True
                if not confirm:
                    time.sleep(0.1)
            return False
        finally:
            if player.poll() is None:
                player.terminate()
                try:
                    player.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    player.kill()
                    player.wait()


def setup(config, path, force=False, clock=time.monotonic, say=prompt):
    """Return True to start YAC, False after requesting inactivity shutdown."""
    settings = config['launcher'] if config.has_section('launcher') else {}
    if settings.get('access_mode', 'both') == 'braille':
        return True
    volume = int(settings.get('volume', '70'))
    if not 1 <= volume <= 100:
        raise ValueError('Audio setup volume must be 1..100.')
    current = outputs()
    selected = next((item for item in current
                     if item.card == settings.get('audio_card') and
                     str(item.device) == settings.get('audio_device')), None)
    if not force and settings.get('audio_setup_complete', '').lower() in ('yes', 'true', '1') and selected:
        helper('apply', card=selected.card, device=selected.device, volume=volume)
        return True
    if not sys.stdin.isatty():
        raise RuntimeError('Run audio setup from an interactive console.')
    # Stop Speakup's backend during direct hardware tests; restore it on every exit.
    helper('begin')
    deadline = clock() + 300
    try:
        while clock() < deadline:
            current = outputs()  # Also finds a speaker plugged in during setup.
            if not current:
                if enter(min(1, max(0, deadline - clock()))):
                    print('No audio outputs detected. Connect a speaker.')
                continue
            for item in current:
                if clock() >= deadline:
                    break
                words = 'Audio setup. Press Enter if you can hear this.'
                if clock() >= deadline - 60:
                    words += ' No response received. The Pi will shut down within one minute.'
                print(f'{words} Output: {item.name}, device {item.device}.', flush=True)
                try:
                    helper('probe', card=item.card, device=item.device, volume=volume)
                    confirmed = say(item, words, deadline)
                except (OSError, subprocess.SubprocessError, RuntimeError) as error:
                    print(f'Cannot test {item.name}: {error}', flush=True)
                    confirmed = False
                if confirmed:
                    helper('apply', card=item.card, device=item.device, volume=volume)
                    save(config, path, item)
                    print('Audio output saved. Starting YAC.', flush=True)
                    return True
        print('No audio confirmation received. Shutting down the Pi.', flush=True)
    finally:
        helper('end')
    result = subprocess.run(['sudo', '-n', '/usr/bin/systemctl', 'poweroff'], timeout=20)
    if result.returncode:
        raise RuntimeError('Automatic shutdown failed. Check the poweroff sudo permission.')
    return False
