"""Download published YAC beta releases without Git (GPL-3.0-only)."""
import hashlib
import json
import logging
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
import zipfile

REPOSITORY = 'm0ebp-Gena/YAC'
API = 'https://api.github.com/repos/' + REPOSITORY + '/releases?per_page=100'
MAX_ARCHIVE = 64 * 1024 * 1024
LOG = logging.getLogger('yac.update')
LOG.addHandler(logging.NullHandler())


def fetch(url, limit):
    request = urllib.request.Request(url, headers={'User-Agent': 'yac-update', 'Accept': 'application/vnd.github+json'})
    with urllib.request.urlopen(request, timeout=30) as response:
        if urllib.parse.urlparse(response.geturl()).scheme != "https":
            raise ValueError("Insecure download redirect.")
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError('Download exceeds the expected size.')
    return data


def newest_release(releases):
    candidates = [r for r in releases if not r.get('draft') and r.get('published_at')]
    if not candidates:
        raise ValueError('No published YAC update was found.')
    return max(candidates, key=lambda r: r['published_at'])


def asset_pair(release, windows=False):
    assets = {a['name']: a for a in release.get('assets', [])}
    platform = 'win' if windows else 'mac-linux'
    names = [n for n in assets if re.fullmatch(
        r'yac-' + platform + r'-\d{4}-\d{2}-\d{2}(?:-r\d+)?\.zip', n)]
    if not names:
        names = [n for n in assets if
             (bool(re.fullmatch(r'YAC-(?!source-)[A-Za-z0-9-]+-\d{4}-\d{2}-\d{2}\.zip', n))
              if windows else n == 'yac-source.zip' or bool(re.fullmatch(r'YAC-source-\d{4}-\d{2}-\d{2}\.zip', n)))]
    if len(names) != 1:
        raise ValueError('The release has no unambiguous ' + ('Windows' if windows else 'source') + ' package.')
    name = names[0]
    checksum = next((n for n in (name + '.sha256', name[:-4] + '.sha256') if n in assets), None)
    if checksum is None:
        raise ValueError('The release is missing its package checksum.')
    pair = assets[name], assets[checksum]
    for asset in pair:
        url = urllib.parse.urlparse(asset['browser_download_url'])
        prefix = '/' + REPOSITORY + '/releases/download/'
        if url.scheme != 'https' or url.netloc != 'github.com' or not url.path.startswith(prefix):
            raise ValueError('Unexpected release download address.')
    return pair


def extract_source(data, target):
    import io
    with zipfile.ZipFile(io.BytesIO(data)) as package:
        members = package.infolist()
        if not members or len(members) > 20000 or sum(i.file_size for i in members) > 128 * 1024 * 1024:
            raise ValueError('Invalid source archive size.')
        roots = set()
        seen = set()
        for item in members:
            path = PurePosixPath(item.filename)
            if path.is_absolute() or '..' in path.parts or '\\' in item.filename or ':' in item.filename or not path.parts:
                raise ValueError('Unsafe source archive path.')
            if stat.S_ISLNK(item.external_attr >> 16) or item.filename in seen:
                raise ValueError('Unexpected link or duplicate in source archive.')
            seen.add(item.filename)
            roots.add(path.parts[0])
        if len(roots) != 1:
            raise ValueError('Expected one source folder.')
        source = target / next(iter(roots))
        required = ('yac.py', 'install_yac.py', 'install-yac.sh', 'modules/__init__.py')
        if not all(source.name + '/' + name in seen for name in required):
            raise ValueError('Incomplete YAC source package.')
        package.extractall(target)
    return source


def read_key():
    if sys.platform == 'win32':
        import msvcrt
        key = msvcrt.getwch()
        if key in ('\x00', '\xe0'):
            msvcrt.getwch()
            return '\x00'
        return key
    import termios
    import tty
    fd = sys.stdin.fileno()
    previous = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        return sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, previous)


def clean_changes(text):
    # Release text is display data, never terminal escape sequences or commands.
    return ''.join(c for c in text if c in '\n\t' or (c.isprintable() and c != '\x7f'))[:30000]


def restore(destination, backup, names):
    """Restore program files after failed installation; leave settings and venv alone."""
    for name in names:
        target = destination / name
        if target.is_symlink():
            target.unlink()
        elif target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()
        saved = backup / name
        if saved.is_dir():
            shutil.copytree(saved, target, symlinks=True)
        elif saved.is_file():
            shutil.copy2(saved, target)


def run(destination, key=read_key, *, selected_release=None):
    if selected_release is None:
        print('Checking for YAC updates over the internet...', flush=True)
        release = newest_release(json.loads(fetch(API, 2 * 1024 * 1024)))
        marker = destination / 'release.json'
        current = json.loads(marker.read_text()) if marker.is_file() else {}
        if current.get('tag') == release['tag_name'] or current.get('published_at', '') >= release['published_at']:
            print('YAC is up to date.')
            return 0
    else:
        release = selected_release
    archive, checksum = asset_pair(release)
    while selected_release is None:
        print('A new YAC update is available. r read changes; q cancel; Space install.', end='', flush=True)
        choice = key().casefold()
        print()
        if choice in {'q', '\x03', '\x04', ''}:
            print('Cancelled.')
            return 0
        if choice == 'r':
            print(clean_changes(release.get('body') or 'No release notes supplied.'))
        elif choice == ' ':
            break
    from modules.update_lock import application_lock
    with application_lock(destination, exclusive=True):
        data = fetch(archive['browser_download_url'], MAX_ARCHIVE)
        expected = fetch(checksum['browser_download_url'], 4096).decode('ascii').split()
        if len(expected) != 2 or expected[1].lstrip('*') != archive['name'] or not re.fullmatch('[a-fA-F0-9]{64}', expected[0]):
            raise ValueError('Invalid source checksum file.')
        if hashlib.sha256(data).hexdigest() != expected[0].lower():
            raise ValueError('Download checksum failed; YAC was not changed.')
        with tempfile.TemporaryDirectory(prefix='yac-update-') as temporary:
            source = extract_source(data, Path(temporary))
            # The installer uses this metadata only after successful setup.
            (source / 'release.json').write_text(json.dumps({'tag': release['tag_name'], 'published_at': release['published_at']}))
            protected = ['yac.py', 'modules', 'lang', 'rad_cmds', 'doc', 'LICENSE', 'COPYING',
                         'yac.ini.example', 'error-codes.txt',
                         'changelog.txt', 'update_yac.py', 'release.json', 'run-yac', 'update-yac',
                         'LINUX-MACOS-SETUP.txt', 'KEY-BINDINGS-English.txt', 'TASTENBELEGUNG-Deutsch.txt',
                         'SKROTY-KLAWISZOWE-Polski.txt', 'TECLAS-Espanol.txt']
            backup = Path(temporary) / 'backup'
            backup.mkdir()
            for name in protected:
                original = destination / name
                if original.is_symlink():
                    raise ValueError('Unexpected installation link: ' + name)
                if original.is_dir():
                    shutil.copytree(original, backup / name, symlinks=True)
                elif original.is_file():
                    shutil.copy2(original, backup / name)
            try:
                arguments = {'capture_output': True, 'text': True} if selected_release is not None else {}
                result = subprocess.run([sys.executable, str(source / 'install_yac.py'), '--update'], check=False, **arguments)
            except OSError:
                restore(destination, backup, protected)
                raise
            if result.returncode:
                LOG.error('Source installer failed: tag=%s exit=%s stdout=%s stderr=%s', release.get('tag_name', '?'), result.returncode, getattr(result, 'stdout', '') or '', getattr(result, 'stderr', '') or '')
                restore(destination, backup, protected)
            if result.returncode:
                if selected_release is None:
                    print('Update did not complete. Please keep the messages above for support.')
                return result.returncode
    if selected_release is None:
        print('YAC update installed. Start YAC when ready.')
    return 0


def windows_main(destination):
    from modules.windows_update import run
    try:
        return run(destination)
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, RuntimeError) as error:
        print('Could not update YAC: ' + str(error))
        return 1
    except KeyboardInterrupt:
        print('\nCancelled.')
        return 0


def main():
    if sys.platform not in {'linux', 'darwin'} or os.geteuid() == 0:
        print('Run update-yac as your normal user on Linux or macOS, without sudo.')
        return 1
    if not sys.stdin.isatty():
        print('Run update-yac in an interactive terminal.')
        return 1
    try:
        destination = Path(__file__).resolve().parent
        if destination != (Path.home() / ("Applications" if sys.platform == "darwin" else ".local") / "yac").resolve():
            raise ValueError('Run the installed update-yac command, not the extracted source script.')
        return run(destination)
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, RuntimeError) as error:
        print('Could not update YAC: ' + str(error))
        return 1
    except KeyboardInterrupt:
        print('\nCancelled.')
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
