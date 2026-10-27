from pathlib import Path
import zipfile
import argparse
import re
import hashlib
from datetime import date
from modules.build_outputs import publish
from modules.package_layout import LANGUAGES, documents
import shutil

root = Path(__file__).resolve().parent
parser = argparse.ArgumentParser(description="Create and verify a dated YAC demo ZIP.")
parser.add_argument('--date', default=date.today().isoformat())
parser.add_argument("--source", type=Path, default=root / "builds/.work/demo-dist/YAC")
parser.add_argument("--include-demo", action="store_true", help="Publish the staged runnable folder with the ZIP")
parser.add_argument('--stage-only', action='store_true', help='Verify and stage without publishing release artifacts')
parser.add_argument('--revision', type=int, default=0, help='Same-day release revision')
args = parser.parse_args()
if args.revision < 0:
    parser.error('revision must be nonnegative')
release_suffix = '-r' + str(args.revision) if args.revision else ''
date.fromisoformat(args.date)
source = args.source.resolve()
version_match = re.search(r'^VERSION\s*=\s*"([^"]+)"', (root / 'yac.py').read_text(encoding='utf-8-sig'), re.MULTILINE)
if version_match is None:
    raise RuntimeError('Could not read the YAC version from yac.py')
version = re.sub(r'[^A-Za-z0-9]+', '-', version_match.group(1)).strip('-')
folder = 'yac-win-' + args.date + release_suffix
staging = root / 'builds/.work/packages'
staging.mkdir(parents=True, exist_ok=True)
archive = staging / (folder + '.zip')
expected_settings = b'[yac]\nplatform=\nlang=\ncall=\ndebug=true\n'
if (source / 'yac.ini').read_bytes().replace(b'\r\n', b'\n') != expected_settings:
    raise RuntimeError('Package settings must be clean, with no personal preferences or radio devices')
expected_files = {
    'yac.ini.example', 'error-codes.txt',
    'LICENSE', 'COPYING', 'changelog.txt',
    'YAC-' + version + '.exe', 'yac.ini', 'release.json',
}
if {path.name for path in source.iterdir()} != expected_files | {'_internal', 'lang', 'rad_cmds', 'doc'}:
    raise RuntimeError('Unexpected files in the demo folder; build a clean package before distributing')
release_guides = {'CWKit-LICENSE.txt', 'AUDIO-LICENSES.txt', 'decoder-controls.md', 'split-controls.md',
                  'antenna-controls.md', 'tuner-controls.md'}
release_guides.update(path.name for path in (root / 'doc').iterdir()
                     if path.is_file() and path.suffix in {'.md', '.html'})
release_details = root / 'doc' / ('in-this-release-' + args.date + '.txt')
if release_details.is_file():
    release_guides.add(release_details.name)
if {path.name for path in (source / 'doc').iterdir()} != {'supported-radios', *LANGUAGES.values()} | release_guides:
    raise RuntimeError('Unexpected documentation in the demo folder')
for name in release_guides:
    if (source / 'doc' / name).read_bytes() != (root / 'doc' / name).read_bytes():
        raise RuntimeError('Missing or stale release guide: ' + name)
for relative, original in documents(root, 'win').items():
    if (source / relative).read_bytes() != original.read_bytes():
        raise RuntimeError('Missing or stale language document: ' + str(relative))
for directory in ('lang', 'rad_cmds', 'doc/supported-radios'):
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
            package.write(path, path.relative_to(source).as_posix())
with zipfile.ZipFile(archive) as package:
    assert package.testzip() is None
    assert 'YAC-' + version + '.exe' in package.namelist()
    guides = {
        "yac.ini.example": "yac.ini.example",
        "error-codes.txt": "error-codes.txt",
        "LICENSE": "LICENSE",
        "COPYING": "COPYING",
        "changelog.txt": "changelog.txt",
    }
    for destination_name, source_name in guides.items():
        assert package.read(destination_name) == (root / source_name).read_bytes()
    for relative, original in documents(root, 'win').items():
        assert package.read(relative.as_posix()) == original.read_bytes()
    assert not any(name.endswith(('/START-HERE.txt', '/START-HERE-DE.txt', '/START-HERE-PL.txt')) for name in package.namelist())
    for model in ('ic-705', 'ic-7300', 'ic-7300mk2', 'ic-9700', 'ic-7600'):
        assert 'rad_cmds/icom/CI-V/models/' + model + '/profile.json' in package.namelist()
    assert 'rad_cmds/yaesu/CAT/models/0840/set/dcs_polarity' in package.namelist()
    assert package.read('yac.ini').replace(b'\r\n', b'\n') == expected_settings
    assert 'YAC-' + version + '.exe' in package.namelist()
checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
archive.with_suffix('.sha256').write_text(checksum + '  ' + archive.name + '\n', encoding='ascii')
artifacts = [archive, archive.with_suffix('.sha256')]
legacy = staging / ('YAC-' + version + release_suffix + '-' + args.date + '.zip')
with zipfile.ZipFile(archive) as current, zipfile.ZipFile(legacy, 'w', zipfile.ZIP_DEFLATED) as compatibility:
    for name in current.namelist():
        compatibility.writestr(folder + '/' + name, current.read(name))
legacy_checksum = legacy.with_suffix('.sha256')
legacy_checksum.write_text(hashlib.sha256(legacy.read_bytes()).hexdigest() + '  ' + legacy.name + '\n', encoding='ascii')
artifacts.extend([legacy, legacy_checksum])
if args.include_demo:
    artifacts.append(source)
outputs = artifacts if args.stage_only else publish(root, args.date, artifacts)
archive = outputs[0]
print(f'Created and verified {archive}: {archive.stat().st_size:,} bytes')
if args.include_demo:
    print('Runnable demo: ' + str(outputs[-1]))
