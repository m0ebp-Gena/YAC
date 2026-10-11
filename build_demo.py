"""Build a portable demo ZIP using PyInstaller installed in .build-deps."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import argparse
import re
from datetime import date

root = Path(__file__).resolve().parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--date", default=date.today().isoformat(), help="Release date (YYYY-MM-DD)")
parser.add_argument("--dist-dir", default="demo-dist", help="Build output directory")
args = parser.parse_args()
date.fromisoformat(args.date)
env = os.environ.copy()
env["PYTHONPATH"] = str(root / ".build-deps")
subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
                "--onedir", "--console", "--name", "YAC", "--distpath", args.dist_dir,
                "--workpath", ".demo-build", "--specpath", ".demo-build",
                "--paths", str(root), "--hidden-import", "serial.tools.list_ports_windows",
                "demo_launcher.py"], cwd=root, env=env, check=True)
destination = root / args.dist_dir / "YAC"
for language in ("en", "de", "pl", "es"):
    shutil.copytree(root / "lang" / language, destination / "lang" / language, dirs_exist_ok=True)
shutil.copytree(root / "rad_cmds", destination / "rad_cmds", dirs_exist_ok=True)
(destination / "yac.ini").write_text("[yac]\nplatform=\nlang=\ncall=\ndebug=true\n", encoding="utf-8")
guides = {
    "demo-start-here.txt": "START-HERE-English.txt",
    "demo-start-here-de.txt": "HIER-STARTEN-Deutsch.txt",
    "demo-start-here-pl.txt": "ZACZNIJ-TUTAJ-Polski.txt",
    "demo-start-here-es.txt": "EMPIEZA-AQUI-Espanol.txt",
}
for source_name, destination_name in guides.items():
    shutil.copyfile(root / source_name, destination / destination_name)
subprocess.run([str(destination / "YAC.exe"), "--check-package"], cwd=root, check=True)
version_match = re.search(r'^VERSION\s*=\s*"([^"]+)"', (root / "yac.py").read_text(encoding="utf-8-sig"), re.MULTILINE)
if version_match is None:
    raise RuntimeError("Could not read the YAC version")
version = re.sub(r"[^A-Za-z0-9]+", "-", version_match.group(1)).strip("-")
(destination / "YAC.exe").replace(destination / ("YAC-" + version + ".exe"))
subprocess.run([sys.executable, str(root / "package_demo.py"), "--date", args.date, "--source", str(destination)], cwd=root, check=True)

