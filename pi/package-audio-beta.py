"""Build the separate Pi audio beta with source and image-builder materials."""
from pathlib import Path
import hashlib
import json
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'builds/.work/packages/yac-source.zip'
TARGET = ROOT / 'yac-pi-features-beta-2026-10-22.zip'
START = '''PI FEATURES BETA - 22 OCTOBER 2026

Read pi/doc/pi-features-beta.html or pi/doc/pi-features-beta.md.
All Pi instructions are separate from ordinary YAC documentation.

Quit YAC. On your existing Pi, as user yac, after extracting this ZIP:
  sh pi/install-features-beta.sh

For a fresh image only, use the full pi/install-pi-beta.sh installer instead.

The installer updates YAC and puts the launcher, audio module, helpers and
permissions in place. It preserves your INI and existing login startup.
You do not need to copy individual files manually.

At the Pi's local console, after quitting an existing YAC:
  python3 /home/yac/.local/bin/yac-pi

Press Enter when you hear the English audio setup prompt. The selected
output is saved before YAC starts. Unanswered setup powers off after five
minutes. Hardware testing is still required. No files have been pushed.

YAC also provides s u for updates and, on this image, s w for Wi-Fi setup.
Read pi/doc/pi-wifi.html for setup and the one-command image Wi-Fi cleanup.
'''


def write(path, entries):
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(entries.items()):
            item = zipfile.ZipInfo(name)
            item.compress_type = zipfile.ZIP_DEFLATED
            item.external_attr = (0o100755 if name.endswith('.sh') else 0o100644) << 16
            archive.writestr(item, data)
    with zipfile.ZipFile(path) as archive:
        assert archive.testzip() is None
        assert not any(name.endswith(('/yac.ini', '.pyc', '.log')) for name in archive.namelist())
    Path(str(path) + '.sha256').write_text(hashlib.sha256(path.read_bytes()).hexdigest() + '  ' + path.name + '\n')


entries = {}
with zipfile.ZipFile(SOURCE) as source:
    assert not any('/doc/pi-' in name or '/pi/' in name for name in source.namelist())
    for name in source.namelist():
        relative = name.split('/', 1)[1]
        if relative != 'release.json':
            entries[relative] = source.read(name)
kit = {name: (ROOT / name).read_bytes() for name in ('pi-launcher.py', 'pi_audio.py', 'LICENSE', 'COPYING')}
for path in (ROOT / 'pi').rglob('*'):
    if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc':
        kit[path.relative_to(ROOT).as_posix()] = path.read_bytes()
kit['START-HERE.txt'] = START.encode()
kit['pi-launcher.ini'] = (ROOT / 'pi/doc/pi-launcher.ini.example').read_bytes()
entries.update(kit)
entries['release.json'] = json.dumps({'tag': 'local-pi-features-beta-2026-10-22',
                                     'published_at': '2026-10-22T00:00:00Z',
                                     'local_beta': True}).encode()
for name in list(entries):
    if name.endswith(('.sh', '.py')):
        entries[name] = entries[name].replace(b'\r\n', b'\n')
write(TARGET, entries)
write(ROOT / 'yac-pi-audio-beta-2026-10-22.zip', entries)
print('Created and checked ' + str(TARGET))
