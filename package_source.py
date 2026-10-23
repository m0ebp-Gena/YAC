"""Package the portable Python source for Linux and macOS testing."""
import argparse
from datetime import date
from pathlib import Path
import zipfile
import hashlib
import json
from modules.build_outputs import publish

root = Path(__file__).resolve().parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--date", default=date.today().isoformat())
parser.add_argument("--stage-only", action="store_true", help="Create a checked local package without rotating release artifacts")
args = parser.parse_args()
date.fromisoformat(args.date)
folder = "yac-source-" + args.date
files = [root / name for name in (
    "LICENSE", "COPYING", "changelog.txt", "update_yac.py", "yac.py", "install-yac.sh", "install_yac.py", "requirements.txt", "requirements-decoders.txt",
    "doc/decoder-controls.md", "doc/CWKit-LICENSE.txt",
    "doc/AUDIO-LICENSES.txt",
    "doc/split-controls.md", "doc/antenna-controls.md", "doc/tuner-controls.md",
    "yac.ini.example",
    "KEY-BINDINGS-English.txt", "TASTENBELEGUNG-Deutsch.txt",
    "SKROTY-KLAWISZOWE-Polski.txt", "TECLAS-Espanol.txt",
    "doc/linux-macos-setup.txt", "doc/debian-trixie-setup.txt",
    "BRAILLE-FS-START-HERE.txt", "doc/ic-7600-support.md", "doc/ic-9700-support.md",
    "doc/filter-controls.md",
    "doc/ts-480-support.md",
    "doc/mic-gain.md", "doc/speech-processor.txt", "doc/settings-controls.md",
)]
files.extend(path for path in (root / 'doc').iterdir()
             if path.is_file() and path.suffix in {'.md', '.html'})
files = list(set(files))
for directory in [root / "modules", root / "rad_cmds", root / "doc/supported-radios", *(root / "lang" / language for language in ("en", "de", "pl", "es"))]:
    files.extend(path for path in directory.rglob("*") if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc")
staging = root / 'builds/.work/packages'
staging.mkdir(parents=True, exist_ok=True)
archive = staging / "yac-source.zip"
with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as package:
    package.writestr(folder + '/release.json', json.dumps({'tag': 'v001-beta-' + args.date, 'published_at': args.date + 'T00:00:00Z'}))
    for path in sorted(files):
        entry = zipfile.ZipInfo((Path(folder) / path.relative_to(root)).as_posix())
        entry.external_attr = (0o100755 if path.name == "install-yac.sh" else 0o100644) << 16
        entry.compress_type = zipfile.ZIP_DEFLATED
        package.writestr(entry, path.read_bytes())
with zipfile.ZipFile(archive) as package:
    assert package.testzip() is None
    assert b"\r" not in package.read(folder + "/install-yac.sh")
    assert package.read(folder + "/yac.py") == (root / "yac.py").read_bytes()
    for guide in (root / 'doc/supported-radios').glob('*.txt'):
        assert package.read(folder + '/doc/supported-radios/' + guide.name) == guide.read_bytes()
    for required in ("modules/dummy_radio.py", "BRAILLE-FS-START-HERE.txt", "lang/es/labels/l107",
                     "KEY-BINDINGS-English.txt", "TASTENBELEGUNG-Deutsch.txt",
                     "SKROTY-KLAWISZOWE-Polski.txt", "TECLAS-Espanol.txt"):
        assert package.read(folder + "/" + required) == (root / required).read_bytes()
    assert not any(name.endswith(("yac.ini", "YAC.exe", ".pyc", ".log")) for name in package.namelist())
checksum = Path(str(archive) + '.sha256')
checksum.write_text(hashlib.sha256(archive.read_bytes()).hexdigest() + '  ' + archive.name + '\n', encoding='ascii')
if not args.stage_only:
    archive = publish(root, args.date, [archive, checksum])[0]
print("Created and checked " + str(archive))
