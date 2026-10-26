#!/bin/sh
# Shared source-only update for the Pi beta helpers. No boot/audio changes.
set -eu
cd "$(dirname "$0")/.."
if [ "$(id -u)" = 0 ]; then
    echo 'Run as the normal YAC user, without sudo before the script.'
    exit 1
fi
python3 - <<'PY'
from pathlib import Path
import install_yac
from modules.update_lock import application_lock
target = install_yac.installation_directory(Path.home(), 'linux')
if not (target / 'yac.py').is_file():
    raise SystemExit('Existing YAC was not found. Use the full Pi beta installer for a new image.')
try:
    with application_lock(target, exclusive=True):
        result = install_yac.main(update=True)
except RuntimeError as error:
    raise SystemExit(str(error))
raise SystemExit(result)
PY
