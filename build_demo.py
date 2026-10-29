"""Build a portable demo ZIP using PyInstaller installed in .build-deps."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import argparse
import re
import json
import ssl
from datetime import date
from modules.package_layout import copy_documents

root = Path(__file__).resolve().parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--date", default=date.today().isoformat(), help="Release date (YYYY-MM-DD)")
parser.add_argument("--dist-dir", default="builds/.work/demo-dist", help="Staging directory within builds")
parser.add_argument('--stage-only', action='store_true', help='Build and verify without publishing release artifacts')
parser.add_argument('--revision', type=int, default=0, help='Same-day release revision')
parser.add_argument('--tag', help='GitHub release tag to record in the package')
args = parser.parse_args()
if args.revision < 0:
    parser.error('revision must be nonnegative')
release_suffix = '-r' + str(args.revision) if args.revision else ''
date.fromisoformat(args.date)
staging = (root / args.dist_dir).resolve()
if not staging.is_relative_to((root / 'builds/.work').resolve()):
    raise ValueError('Stage the demo within builds/.work')
env = os.environ.copy()
env["PYTHONPATH"] = str(root / ".build-deps")
ssl_data = []
# This Python runtime's ssl module loads this companion file when creating
# any SSLContext. Preserve it beside the frozen ssl module as well.
runtime_ca = Path(ssl.__file__).with_name('codex-rejected-cas.pem')
if runtime_ca.is_file():
    ssl_data = ['--add-data', str(runtime_ca) + os.pathsep + '.']
subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
                "--onedir", "--console", "--name", "YAC", "--distpath", args.dist_dir,
                "--workpath", "builds/.work/pyinstaller", "--specpath", "builds/.work/pyinstaller",
                "--paths", str(root), "--hidden-import", "serial.tools.list_ports_windows",
                "--add-data", str(root / 'modules/certificates') + os.pathsep + 'modules/certificates',
                "--exclude-module", "numpy",
                *ssl_data, "demo_launcher.py"], cwd=root, env=env, check=True)
destination = root / args.dist_dir / "YAC"
for language in ("en", "de", "pl", "es"):
    shutil.copytree(root / "lang" / language, destination / "lang" / language, dirs_exist_ok=True)
shutil.copytree(root / "rad_cmds", destination / "rad_cmds", dirs_exist_ok=True)
shutil.copytree(root / "doc/supported-radios", destination / "doc/supported-radios", dirs_exist_ok=True)
shutil.copyfile(root / "doc/CWKit-LICENSE.txt", destination / "doc/CWKit-LICENSE.txt")
shutil.copyfile(root / "doc/decoder-controls.md", destination / "doc/decoder-controls.md")
for guide in ('split-controls.md', 'antenna-controls.md', 'tuner-controls.md', 'AUDIO-LICENSES.txt', 'swr-controls.txt'):
    shutil.copyfile(root / 'doc' / guide, destination / 'doc' / guide)
for guide in (root / 'doc').iterdir():
    if guide.is_file() and guide.suffix in {'.md', '.html'}:
        shutil.copyfile(guide, destination / 'doc' / guide.name)
release_details = root / 'doc' / ('in-this-release-' + args.date + '.txt')
if release_details.is_file():
    shutil.copyfile(release_details, destination / 'doc' / release_details.name)
copy_documents(root, destination, 'win')
(destination / "yac.ini").write_text("[yac]\nplatform=\nlang=\ncall=\ndebug=true\n", encoding="utf-8")
(destination / 'release.json').write_text(json.dumps({'tag': args.tag or 'v001-beta-' + args.date + release_suffix,
                                                    'published_at': args.date + 'T00:00:00Z'}))
guides = {
    "yac.ini.example": "yac.ini.example",
    "error-codes.txt": "error-codes.txt",
    "LICENSE": "LICENSE",
    "COPYING": "COPYING",
    "changelog.txt": "changelog.txt",
}
for source_name, destination_name in guides.items():
    shutil.copyfile(root / source_name, destination / destination_name)
subprocess.run([str(destination / "YAC.exe"), "--check-package"], cwd=root, check=True)
version_match = re.search(r'^VERSION\s*=\s*"([^"]+)"', (root / "yac.py").read_text(encoding="utf-8-sig"), re.MULTILINE)
if version_match is None:
    raise RuntimeError("Could not read the YAC version")
version = re.sub(r"[^A-Za-z0-9]+", "-", version_match.group(1)).strip("-")
(destination / "YAC.exe").replace(destination / ("YAC-" + version + ".exe"))
subprocess.run([sys.executable, str(root / "package_demo.py"), "--date", args.date,
                "--source", str(destination), "--revision", str(args.revision), *(['--stage-only'] if args.stage_only else ['--include-demo'])], cwd=root, check=True)

