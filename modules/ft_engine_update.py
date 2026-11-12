"""Install the optional FT8 and FT4 engine from a YAC release."""

import io
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import zipfile

from modules.ini_settings import read_settings
from modules.nexus_ft8 import (LINUX_ENGINE_MACHINES, MACOS_ENGINE_MACHINES, configured_engine,
                              downloaded_engine, engine_target)


ENGINE_FILES = ('jimmy-engine-host', 'Jimmy-Next-LICENSE.txt',
                'Nexus-COPYING.txt', 'Nexus-NOTICE.txt')
ENGINE_TARGETS = (*LINUX_ENGINE_MACHINES, *MACOS_ENGINE_MACHINES)


def asset_name(target):
    return f'yac-ft-engine-{target}.zip'


def offer(root, release):
    from update_yac import checked_asset_pair

    target = engine_target()
    if target is None:
        return None
    name = asset_name(target)
    assets = release.get('assets', [])
    archive = [asset for asset in assets if asset.get('name') == name]
    checksum = [asset for asset in assets if asset.get('name') == name + '.sha256']
    if len(archive) != 1 or len(checksum) != 1:
        return None
    try:
        settings = read_settings(root / 'yac.ini')
        if settings.get('ft_engine', '').strip() or configured_engine(root, settings).is_file():
            return None
        return target, checked_asset_pair(archive[0], checksum[0])
    except (KeyError, ValueError, RuntimeError):
        return None


def check_engine_header(header, target):
    if target in MACOS_ENGINE_MACHINES:
        # Little-endian 64-bit Mach-O, matching CPU type, MH_EXECUTE.
        valid = (len(header) == 20 and header[:4] == b'\xcf\xfa\xed\xfe'
                 and int.from_bytes(header[4:8], 'little') == MACOS_ENGINE_MACHINES[target]
                 and header[12:16] == b'\x02\x00\x00\x00')
    else:
        valid = (len(header) == 20 and header[:6] == b'\x7fELF\x02\x01'
                 and int.from_bytes(header[16:18], 'little') in (2, 3)
                 and int.from_bytes(header[18:20], 'little') == LINUX_ENGINE_MACHINES[target])
    if not valid:
        raise ValueError('Decoder executable does not match the selected platform.')


def install(root, target, assets):
    from update_yac import MAX_ARCHIVE, verified_download

    if target != engine_target():
        raise ValueError('Decoder platform changed before installation.')
    engine = root / downloaded_engine(target)
    destination = engine.parent
    parent = destination.parent
    if parent.is_symlink() or destination.is_symlink():
        raise ValueError('Unexpected decoder installation link.')
    if engine.is_file() and not engine.is_symlink():
        return
    if destination.exists():
        raise ValueError('Decoder installation directory is already in use.')

    data = verified_download(*assets)
    with zipfile.ZipFile(io.BytesIO(data)) as package:
        entries = package.infolist()
        if (sorted(entry.filename for entry in entries) != sorted(ENGINE_FILES)
                or sum(entry.file_size for entry in entries) > MAX_ARCHIVE
                or any(stat.S_ISLNK(entry.external_attr >> 16) or not entry.file_size
                       for entry in entries)):
            raise ValueError('Unexpected contents in decoder archive.')
        with package.open(ENGINE_FILES[0]) as binary:
            check_engine_header(binary.read(20), target)
        parent.mkdir(exist_ok=True)
        # Publish the executable and its notices together. A second downloader
        # can finish concurrently without replacing the first complete install.
        with tempfile.TemporaryDirectory(prefix='.download-', dir=parent) as temporary:
            stage = Path(temporary) / target
            stage.mkdir()
            for name in ENGINE_FILES:
                with package.open(name) as source, (stage / name).open('wb') as output:
                    shutil.copyfileobj(source, output)
            binary = stage / engine.name
            binary.chmod(0o755)
            # A matching ELF can still require libraries absent on this host.
            try:
                result = subprocess.run([str(binary.resolve()), '--list-devices'],
                                        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                        timeout=10)
            except subprocess.TimeoutExpired as error:
                raise RuntimeError('Decoder startup check timed out.') from error
            if result.returncode:
                detail = result.stderr.decode('utf-8', errors='replace').strip()
                raise RuntimeError(f'Decoder startup check failed ({result.returncode}): {detail}')
            try:
                stage.rename(destination)
            except OSError:
                if destination.is_symlink() or engine.is_symlink() or not engine.is_file():
                    raise
