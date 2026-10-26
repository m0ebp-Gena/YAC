from pathlib import Path
import ast
import hashlib
import zipfile
root = Path(__file__).resolve().parents[1]
folder = 'yac-pi-boot-test-2026-10-23'
target = root / (folder + '.zip')
files = {'pi-launcher.py': root / 'pi-launcher.py',
         'START-HERE.txt': root / 'pi/doc/boot-test-start-here.txt',
         'LICENSE': root / 'LICENSE', 'COPYING': root / 'COPYING'}
for name in ('boot-speech.py', 'yac-boot-speech.conf', 'yac-boot-speech-recovery.service', 'yac-boot-speech-recovery.timer'):
    files[name] = root / 'pi' / name
entries = {name: path.read_text(encoding='utf-8-sig').replace('\r\n', '\n').encode() for name, path in files.items()}
for name, data in entries.items():
    if name.endswith('.py'): ast.parse(data, filename=name)
with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
    for name, data in entries.items():
        entry = zipfile.ZipInfo(folder + '/' + name)
        entry.external_attr = 0o100644 << 16
        entry.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(entry, data)
with zipfile.ZipFile(target) as archive:
    assert archive.testzip() is None
    for name, data in entries.items(): assert archive.read(folder + '/' + name) == data
    assert not any(n.endswith('.sh') for n in archive.namelist())
Path(str(target) + '.sha256').write_text(hashlib.sha256(target.read_bytes()).hexdigest() + '  ' + target.name + '\n', encoding='ascii')
print(f'Created and checked {target} ({target.stat().st_size} bytes)')
