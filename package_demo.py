from pathlib import Path
import zipfile
import argparse
import re
import hashlib
from datetime import date

root = Path(__file__).resolve().parent
parser = argparse.ArgumentParser(description="Create and verify a dated YAC demo ZIP.")
parser.add_argument('--date', default=date.today().isoformat())
args = parser.parse_args()
date.fromisoformat(args.date)
source = root / 'demo-dist' / 'YAC'
version_match = re.search(r'^VERSION\s*=\s*"([^"]+)"', (root / 'yac.py').read_text(encoding='utf-8-sig'), re.MULTILINE)
if version_match is None:
    raise RuntimeError('Could not read the YAC version from yac.py')
version = re.sub(r'[^A-Za-z0-9]+', '-', version_match.group(1)).strip('-')
folder = 'YAC-' + version + '-' + args.date
archive = root / (folder + '.zip')
expected_settings = b'[yac]\nplatform=\nlang=\ncall=\ndebug=true\n'
if (source / 'yac.ini').read_bytes().replace(b'\r\n', b'\n') != expected_settings:
    raise RuntimeError('Package settings must be clean, with no personal preferences or radio devices')
expected_files = {
    'YAC-' + version + '.exe', 'yac.ini', 'START-HERE-English.txt',
    'HIER-STARTEN-Deutsch.txt', 'ZACZNIJ-TUTAJ-Polski.txt',
}
if {path.name for path in source.iterdir()} != expected_files | {'_internal', 'lang', 'rad_cmds'}:
    raise RuntimeError('Unexpected files in the demo folder; build a clean package before distributing')
for directory in ('lang', 'rad_cmds'):
    expected_data = {
        path.relative_to(root / directory)
        for path in (root / directory).rglob('*')
        if path.is_file() and '__pycache__' not in path.parts
    }
    actual_data = {
        path.relative_to(source / directory)
        for path in (source / directory).rglob('*') if path.is_file()
    }
    if actual_data != expected_data:
        raise RuntimeError('Missing or stale package data in ' + directory)
    for relative in expected_data:
        if (source / directory / relative).read_bytes() != (root / directory / relative).read_bytes():
            raise RuntimeError('Package data differs from source: ' + str(relative))
with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as package:
    for path in sorted(source.rglob('*')):
        if path.is_file():
            package.write(path, str(Path(folder) / path.relative_to(source)))
with zipfile.ZipFile(archive) as package:
    assert package.testzip() is None
    assert {name.split('/')[0] for name in package.namelist()} == {folder}
    guides = {
        "START-HERE-English.txt": "demo-start-here.txt",
        "HIER-STARTEN-Deutsch.txt": "demo-start-here-de.txt",
        "ZACZNIJ-TUTAJ-Polski.txt": "demo-start-here-pl.txt",
    }
    for destination_name, source_name in guides.items():
        assert package.read(folder + '/' + destination_name) == (root / source_name).read_bytes()
    assert not any(name.endswith(('/START-HERE.txt', '/START-HERE-DE.txt', '/START-HERE-PL.txt')) for name in package.namelist())
    for model in ('ic-705', 'ic-7300', 'ic-7300mk2'):
        assert folder + '/rad_cmds/icom/CI-V/models/' + model + '/profile.json' in package.namelist()
    assert folder + '/rad_cmds/yaesu/CAT/models/0840/set/dcs_polarity' in package.namelist()
    assert package.read(folder + '/yac.ini').replace(b'\r\n', b'\n') == expected_settings
    assert folder + '/YAC-' + version + '.exe' in package.namelist()
checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
archive.with_suffix('.sha256').write_text(checksum + '  ' + archive.name + '\n', encoding='ascii')
print(f'Created and verified {archive.name}: {archive.stat().st_size:,} bytes')
