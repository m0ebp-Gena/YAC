"""Shared user-document layout for portable Windows and Mac/Linux packages."""
from pathlib import Path
import shutil

LANGUAGES = {'en': 'English', 'de': 'Deutsch', 'es': 'Espanol', 'pl': 'Polski'}
CHARTS = {'en': 'KEY-BINDINGS-English.txt', 'de': 'TASTENBELEGUNG-Deutsch.txt',
          'es': 'TECLAS-Espanol.txt', 'pl': 'SKROTY-KLAWISZOWE-Polski.txt'}


def documents(root, platform):
    """Map repository sources to their language-specific package destinations."""
    result = {}
    for language, directory in LANGUAGES.items():
        base = Path('doc') / directory
        platforms = ('win',) if platform == 'win' else ('mac', 'linux')
        for system in platforms:
            path = base / ('START-HERE-' + system + '.txt')
            result[path] = root / path
        result[base / CHARTS[language]] = root / CHARTS[language]
    for name in ('linux-macos-setup.txt', 'debian-trixie-setup.txt'):
        if platform != 'win':
            result[Path('doc/English') / name] = root / 'doc' / name
    result[Path('doc/English/BRAILLE-FS-START-HERE.txt')] = root / 'BRAILLE-FS-START-HERE.txt'
    return result


def copy_documents(root, destination, platform):
    for relative, source in documents(root, platform).items():
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
