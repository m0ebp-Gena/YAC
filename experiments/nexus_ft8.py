"""Run the Nexus receive experiment from its original script path."""

from pathlib import Path
from runpy import run_path


if __name__ == '__main__':
    run_path(str(Path(__file__).resolve().parents[1] / 'modules/nexus_ft8.py'), run_name='__main__')
