from pathlib import Path
import zipfile
import ast
import hashlib
import argparse
from datetime import date
root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--date', required=True)
parser.add_argument('--suffix', default='')
args = parser.parse_args()
date.fromisoformat(args.date)
folder = 'yac-pi-complete-' + args.date + args.suffix
target = root / (folder + '.zip')
entries = {}
with zipfile.ZipFile(root / 'builds/.work/packages/yac-source.zip') as source:
    for name in source.namelist():
        if not name.endswith('/'):
            relative = name.split('/', 1)[1]
            entries[relative] = source.read(name)
for name in ('install.sh', 'pi-launcher.py', 'pi_audio.py', 'pi/audio-settings.py', 'pi/speakup-settings.py', 'pi/wifi-settings.py', 'pi/yac-speakup-restore.service', 'pi/doc/pi-launcher.ini.example'):
    entries[name] = (root / name).read_bytes()
entries['BUILD-INFO.txt'] = ('Pi beta build: ' + args.date + args.suffix + '\nIncludes the completed label and control review.\nAll four application languages included.\n').encode('utf-8')
entries['START-HERE.txt'] = (root / 'pi/doc/complete-install-start-here.txt').read_bytes()
for name in ('checklist-core-template.txt', 'checklist-radio-template.txt'):
    entries[name] = (root / 'doc/checklists' / name).read_bytes()
for name in entries:
    if name.endswith(('.py', '.sh')):
        entries[name] = entries[name].decode('utf-8-sig').replace('\r\n', '\n').encode()
    if name.endswith('.py'):
        ast.parse(entries[name], filename=name)
with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
    for name, data in sorted(entries.items()):
        entry = zipfile.ZipInfo(folder + '/' + name)
        entry.external_attr = (0o100755 if name.endswith('.sh') else 0o100644) << 16
        entry.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(entry, data)
with zipfile.ZipFile(target) as archive:
    assert archive.testzip() is None
    names = archive.namelist()
    for name in ('install.sh', 'install-yac.sh', 'install_yac.py', 'pi/wifi-settings.py', 'pi/yac-speakup-restore.service'):
        assert folder + '/' + name in names
    assert {n.split('/')[2] for n in names if n.startswith(folder + '/lang/')} == {'en', 'de', 'pl', 'es'}
    for name in ('install_yac.py', 'modules/lang_sel.py', 'modules/access_control.py', 'pi-launcher.py'):
        assert archive.read(folder + '/' + name) == (root / name).read_bytes().replace(b'\r\n', b'\n')
    script = archive.read(folder + '/install.sh').decode()
    assert not script.startswith('\ufeff') and '\r' not in script
    assert 'python3 install_yac.py --pi\n' in script
    assert 'boot-speech.conf' not in script and 'cw-login-ready' not in script
Path(str(target) + '.sha256').write_text(hashlib.sha256(target.read_bytes()).hexdigest() + '  ' + target.name + '\n', encoding='ascii')
print(f'Created and checked {target}; {len(entries)} files; {target.stat().st_size} bytes')
