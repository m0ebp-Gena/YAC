from pathlib import Path
import zipfile
import argparse
import re
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
    assert b'debug=true' in package.read(folder + '/yac.ini')
print(f'Created and verified {archive.name}: {archive.stat().st_size:,} bytes')
