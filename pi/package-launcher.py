"""Package the real Pi launcher and manual image configuration materials."""
from pathlib import Path
import hashlib
import zipfile
import ast

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / 'yac-pi-launcher-2026-10-23.zip'
folder = 'yac-pi-launcher-2026-10-23'
mapping = {
    'pi-launcher.py': 'pi-launcher.py', 'pi_audio.py': 'pi_audio.py',
    'pi/audio-settings.py': 'pi/audio-settings.py',
    'pi/speakup-settings.py': 'pi/speakup-settings.py',
    'pi/wifi-settings.py': 'pi/wifi-settings.py',
    'pi/clear-image-wifi.py': 'pi/clear-image-wifi.py',
    'pi/yac-speakup-restore.service': 'pi/yac-speakup-restore.service',
    'pi-launcher.ini.example': 'pi/doc/pi-launcher.ini.example',
    'profile-launcher.txt': 'pi/profile-launcher.txt',
    'cw-login-ready.service': 'pi/cw-login-ready.service.example',
    'sudoers-yac.example': 'pi/sudoers-yac.example',
    'START-HERE.txt': 'pi/doc/launcher-kit-start-here.txt',
    'LICENSE': 'LICENSE', 'COPYING': 'COPYING',
}
for name in ('boot-speech.py', 'yac-boot-speech.conf', 'yac-boot-speech-recovery.service', 'yac-boot-speech-recovery.timer'):
    mapping['optional-boot-speech/' + name] = 'pi/' + name
for name in ('de', 'k', '73'):
    mapping['pi/cw/' + name] = 'pi/cw/' + name
entries = {}
for name, source in mapping.items():
    data = (ROOT / source).read_bytes()
    data = data.decode('utf-8-sig').replace('\r\n', '\n').encode()
    if name.endswith('.py'):
        ast.parse(data, filename=name)
    entries[name] = data
with zipfile.ZipFile(TARGET, 'w', zipfile.ZIP_DEFLATED) as archive:
    for name, data in sorted(entries.items()):
        item = zipfile.ZipInfo(folder + '/' + name)
        item.compress_type = zipfile.ZIP_DEFLATED
        item.external_attr = 0o100644 << 16
        archive.writestr(item, data)
with zipfile.ZipFile(TARGET) as archive:
    assert archive.testzip() is None
    assert not any(n.endswith('.sh') for n in archive.namelist())
    profile = archive.read(folder + '/profile-launcher.txt').decode()
    assert len(profile.strip().splitlines()) == 3
    assert 'SSH_CONNECTION' in profile and '/dev/tty1' in profile
    assert 'exec ' not in profile
    for name, source in mapping.items():
        assert archive.read(folder + '/' + name) == (ROOT / source).read_text(encoding='utf-8-sig').replace('\r\n', '\n').encode()
checksum = hashlib.sha256(TARGET.read_bytes()).hexdigest()
Path(str(TARGET) + '.sha256').write_text(checksum + '  ' + TARGET.name + '\n', encoding='ascii')
# Validate normal release contents, without substituting alternate installer or language code.
with zipfile.ZipFile(ROOT / 'yac-source.zip') as archive:
    prefix = 'yac-source-2026-10-23/'
    for name in ('install-yac.sh', 'install_yac.py', 'modules/lang_sel.py', 'modules/access_control.py', 'lang/en/labels/l301'):
        assert archive.read(prefix + name) == (ROOT / name).read_bytes()
    assert {n[len(prefix):].split('/')[1] for n in archive.namelist() if n.startswith(prefix + 'lang/')} == {'en', 'de', 'pl', 'es'}
    assert not any(n.startswith(prefix + 'pi/') or n.endswith('/install.sh') for n in archive.namelist())
print(f'Created and checked {TARGET}: {len(entries)} files, {TARGET.stat().st_size} bytes')
