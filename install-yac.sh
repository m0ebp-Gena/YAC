#!/bin/sh
# Run from an extracted YAC source package: sh install-yac.sh
set -eu
if ! command -v python3 >/dev/null 2>&1; then
    echo 'Python 3 was not found.'
    echo 'Consult your package manager instructions to install Python 3.10 or newer, with venv and pip support, then run this script again.'
    echo 'On macOS, Python is also available from https://www.python.org/downloads/macos/.'
    exit 1
fi
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
    echo 'YAC requires Python 3.10 or newer. Consult your package manager instructions and run this script again after installing it.'
    exit 1
fi
script_directory=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
exec python3 "$script_directory/install_yac.py"
