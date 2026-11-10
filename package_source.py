"""Package the portable Python source for Linux and macOS testing."""
import argparse
from datetime import date
from pathlib import Path
import zipfile
import hashlib
import json
from modules.build_outputs import publish
from modules.ft_engine_update import check_engine_header
from modules.nexus_ft8 import BUNDLED_ENGINES
from modules.package_layout import documents
import shutil

root = Path(__file__).resolve().parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--date", default=date.today().isoformat())
parser.add_argument("--stage-only", action="store_true", help="Create a checked local package without rotating release artifacts")
parser.add_argument('--revision', type=int, default=0, help='Same-day release revision')
parser.add_argument('--tag', help='GitHub release tag to record in the package')
parser.add_argument('--nexus-linux-arm64', type=Path, help='Include a verified Linux ARM64 engine in a local test package')
parser.add_argument('--nexus-macos-arm64', type=Path, help='Include a verified Apple Silicon engine in a local test package')
args = parser.parse_args()
if args.revision < 0:
    parser.error('revision must be nonnegative')
engines = {target: path for target, path in (('linux-arm64', args.nexus_linux_arm64),
                                           ('macos-arm64', args.nexus_macos_arm64)) if path is not None}
if engines and not args.stage_only:
    parser.error('bundled test engines require --stage-only')
for target, engine in engines.items():
    with engine.open('rb') as stream:
        check_engine_header(stream.read(20), target)
release_suffix = '-r' + str(args.revision) if args.revision else ''
date.fromisoformat(args.date)
folder = "yac-mac-linux-" + args.date + release_suffix
files = [root / name for name in (
    "LICENSE", "COPYING", "changelog.txt", "update_yac.py", "yac.py", "install-yac.sh", "install_yac.py", "requirements.txt", "requirements-decoders.txt",
    "doc/decoder-controls.md", "doc/CWKit-LICENSE.txt",
    "doc/AUDIO-LICENSES.txt",
    "doc/split-controls.md", "doc/antenna-controls.md", "doc/tuner-controls.md",
    "yac.ini.example", "error-codes.txt",
    "doc/ic-7600-support.md", "doc/ic-9700-support.md",
    "doc/filter-controls.md",
    "doc/ts-480-support.md",
    "doc/mic-gain.md", "doc/speech-processor.txt", "doc/settings-controls.md", "doc/swr-controls.txt",
)]
files.extend(path for path in (root / 'doc').iterdir()
             if path.is_file() and path.suffix in {'.md', '.html'})
release_details = root / 'doc' / ('in-this-release-' + args.date + '.txt')
if release_details.is_file():
    files.append(release_details)
files = list(set(files))
for directory in [root / "modules", root / "rad_cmds", root / "doc/supported-radios", *(root / "lang" / language for language in ("en", "de", "pl", "es"))]:
    files.extend(path for path in directory.rglob("*") if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc")
staging = root / 'builds/.work/packages'
staging.mkdir(parents=True, exist_ok=True)
archive = staging / (folder + '.zip')
with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as package:
    package.writestr(folder + '/release.json', json.dumps({'tag': args.tag or 'v001-' + args.date + release_suffix, 'published_at': args.date + 'T00:00:00Z'}))
    for target, engine in engines.items():
        bundled = BUNDLED_ENGINES[target]
        entry = zipfile.ZipInfo(folder + '/' + bundled.as_posix())
        entry.external_attr = 0o100755 << 16
        entry.compress_type = zipfile.ZIP_DEFLATED
        package.writestr(entry, engine.read_bytes())
        jimmy = root / 'builds/.work/nexus-channel/JimmyNext'
        for name, notice in (
            ('Jimmy-Next-LICENSE.txt', jimmy / 'LICENSE'),
            ('Nexus-COPYING.txt', jimmy / 'EngineHost/.nexus-src/COPYING'),
            ('Nexus-NOTICE.txt', jimmy / 'EngineHost/.nexus-src/NOTICE'),
        ):
            package.write(notice, folder + '/' + (bundled.parent / name).as_posix())
    for path in sorted(files):
        entry = zipfile.ZipInfo((Path(folder) / path.relative_to(root)).as_posix())
        mode = 0o100755 if path.name == "install-yac.sh" else 0o100444 if path.name.endswith('-template.txt') else 0o100644
        entry.external_attr = mode << 16
        entry.compress_type = zipfile.ZIP_DEFLATED
        package.writestr(entry, path.read_bytes())
    # The repository's install.sh is the complete Pi installer. The general
    # Mac/Linux package exposes the short command without shipping Pi setup.
    entry = zipfile.ZipInfo(folder + '/install.sh')
    entry.external_attr = 0o100755 << 16
    entry.compress_type = zipfile.ZIP_DEFLATED
    package.writestr(entry, (root / 'install-yac.sh').read_bytes().replace(b'install-yac.sh', b'install.sh'))
    for relative, source in sorted(documents(root, 'mac-linux').items()):
        entry = zipfile.ZipInfo(folder + '/' + relative.as_posix())
        entry.external_attr = (0o100444 if source.name.endswith('-template.txt') else 0o100644) << 16
        entry.compress_type = zipfile.ZIP_DEFLATED
        package.writestr(entry, source.read_bytes())
with zipfile.ZipFile(archive) as package:
    assert package.testzip() is None
    assert b"\r" not in package.read(folder + "/install-yac.sh")
    assert package.read(folder + '/install.sh') == (root / 'install-yac.sh').read_bytes().replace(b'install-yac.sh', b'install.sh')
    assert 'install_yac.py --pi' not in package.read(folder + '/install.sh').decode()
    assert package.read(folder + "/yac.py") == (root / "yac.py").read_bytes()
    for guide in (root / 'doc/supported-radios').glob('*.txt'):
        assert package.read(folder + '/doc/supported-radios/' + guide.name) == guide.read_bytes()
    for required in ("modules/__init__.py", "modules/dummy_radio.py", "lang/es/labels/l107"):
        assert package.read(folder + "/" + required) == (root / required).read_bytes()
    for relative, source in documents(root, 'mac-linux').items():
        assert package.read(folder + '/' + relative.as_posix()) == source.read_bytes()
    assert not any(name.endswith(("yac.ini", "YAC.exe", ".pyc", ".log")) for name in package.namelist())
    assert not any(name.endswith('-template.txt') for name in package.namelist()), 'Private test template in public package'
# Validate the actual release artifact through the same extraction path used on update.
import tempfile
import update_yac
with tempfile.TemporaryDirectory(prefix='yac-source-check-') as temporary:
    extracted = update_yac.extract_source(archive.read_bytes(), Path(temporary))
    assert (extracted / 'modules/__init__.py').is_file()
    for target, engine in engines.items():
        assert (extracted / BUNDLED_ENGINES[target]).read_bytes() == engine.read_bytes()
checksum = Path(str(archive) + '.sha256')
checksum.write_text(hashlib.sha256(archive.read_bytes()).hexdigest() + '  ' + archive.name + '\n', encoding='ascii')
if not engines:
    # Older installed updaters require this exact asset name.
    legacy = staging / 'yac-source.zip'
    shutil.copyfile(archive, legacy)
    legacy_checksum = Path(str(legacy) + '.sha256')
    legacy_checksum.write_text(hashlib.sha256(legacy.read_bytes()).hexdigest() + '  ' + legacy.name + '\n', encoding='ascii')
    if not args.stage_only:
        archive = publish(root, args.date, [archive, checksum, legacy, legacy_checksum])[0]
print("Created and checked " + str(archive))
