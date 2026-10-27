"""Verified portable Windows updates after the running EXE exits. GPL-3.0-only."""
import base64
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile

from modules.update_control import REQUEST

DATA_NAMES = {'_internal', 'lang', 'rad_cmds', 'doc', 'LICENSE', 'COPYING', 'changelog.txt',
              'yac.ini.example', 'error-codes.txt',
              'release.json', 'yac.ini', 'KEY-BINDINGS-English.txt', 'TASTENBELEGUNG-Deutsch.txt',
              'SKROTY-KLAWISZOWE-Polski.txt', 'TECLAS-Espanol.txt', 'START-HERE-English.txt',
              'HIER-STARTEN-Deutsch.txt', 'ZACZNIJ-TUTAJ-Polski.txt', 'EMPIEZA-AQUI-Espanol.txt'}


def extract(data, target):
    with zipfile.ZipFile(io.BytesIO(data)) as package:
        members = package.infolist()
        if not members or len(members) > 20000 or sum(i.file_size for i in members) > 256 * 1024 * 1024:
            raise ValueError('Invalid Windows archive size.')
        roots, seen, programs = set(), set(), set()
        flat = any('/' not in item.filename and re.fullmatch(r'YAC(?:-[A-Za-z0-9-]+)?\.exe', item.filename)
                   for item in members)
        for item in members:
            path = PurePosixPath(item.filename)
            if (not path.parts or path.is_absolute() or '..' in path.parts or
                    '\\' in item.filename or ':' in item.filename):
                raise ValueError('Unsafe Windows archive path.')
            for part in path.parts:
                stem = part.split('.')[0].upper()
                if (part.endswith((' ', '.')) or any(ord(c) < 32 for c in part) or
                        any(c in part for c in '<>"|?*') or
                        stem in {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)),
                                 *(f'LPT{i}' for i in range(1, 10))}):
                    raise ValueError('Unsafe Windows archive filename.')
            key = path.as_posix().casefold()
            if stat.S_ISLNK(item.external_attr >> 16) or key in seen:
                raise ValueError('Windows archive has a link or duplicate path.')
            seen.add(key)
            roots.add(path.parts[0])
            relative = path.parts if flat else path.parts[1:]
            if relative:
                name = relative[0]
                program = bool(re.fullmatch(r'YAC(?:-[A-Za-z0-9-]+)?\.exe', name))
                if name not in DATA_NAMES and not program:
                    raise ValueError('Unexpected Windows package content: ' + name)
                if program:
                    if len(relative) != 1 or item.is_dir():
                        raise ValueError('Invalid Windows executable path.')
                    programs.add(name)
        if (not flat and len(roots) != 1) or len(programs) != 1:
            raise ValueError('Expected one Windows folder and executable.')
        source = target / ('package' if flat else next(iter(roots)))
        prefix = '' if flat else source.name + '/'
        required = ('yac.ini', 'lang/en/labels/l000', 'LICENSE')
        if (not all((prefix + n).casefold() in seen for n in required) or
                not any(n.startswith((prefix + '_internal/').casefold()) for n in seen)):
            raise ValueError('Incomplete Windows package.')
        package.extractall(source if flat else target)
    return source, next(iter(programs))


def literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def installer_script(destination, source, stage, executable, old_executable, pid):
    names = sorted(p.name for p in source.iterdir() if p.name != 'yac.ini')
    if old_executable not in names:
        names.append(old_executable)
    # Paths are literal PowerShell strings; user directory names cannot become code.
    parameters = ('$Destination = ' + literal(destination) + '\n$Source = ' + literal(source) +
                  '\n$Stage = ' + literal(stage) + '\n$Program = ' + literal(executable) +
                  '\n$ParentPid = ' + str(int(pid)) + '\n$Names = @(' +
                  ','.join(literal(n) for n in names) + ')\n')
    return parameters + r'''
$ErrorActionPreference = 'Stop'
$Destination = [IO.Path]::GetFullPath($Destination)
$Stage = [IO.Path]::GetFullPath($Stage)
$Backup = Join-Path $Stage 'backup'
$Changed = [Collections.Generic.List[string]]::new()
$Lock = $null
$Success = $false
function ChildPath($Base, $Name) {
    if ($Name -match '[/\\]' -or $Name -eq '.' -or $Name -eq '..') { throw 'Invalid update filename' }
    $Result = [IO.Path]::GetFullPath((Join-Path $Base $Name))
    if ([IO.Path]::GetDirectoryName($Result) -ne $Base) { throw 'Update path escaped its folder' }
    return $Result
}
try {
    Write-Host 'Waiting for YAC to close before installing the update.'
    $Parent = Get-Process -Id $ParentPid -ErrorAction SilentlyContinue
    if ($Parent) { $Parent.WaitForExit(30000) | Out-Null }
    if (Get-Process -Id $ParentPid -ErrorAction SilentlyContinue) { throw 'YAC has not closed. No update installed.' }
    $Lock = [IO.File]::Open((Join-Path $Destination '.update.lock'), 'OpenOrCreate', 'ReadWrite', 'ReadWrite')
    $Lock.Lock(0, 1)
    New-Item -ItemType Directory -Path $Backup | Out-Null
    foreach ($Name in $Names) {
        $Target = ChildPath $Destination $Name
        $Saved = ChildPath $Backup $Name
        $Incoming = ChildPath $Source $Name
        if (Test-Path -LiteralPath $Target) {
            if ((Get-Item -LiteralPath $Target -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw 'Refusing to replace a linked application file'
            }
            Move-Item -LiteralPath $Target -Destination $Saved
        }
        $Changed.Add($Name)
        if (Test-Path -LiteralPath $Incoming) { Copy-Item -LiteralPath $Incoming -Destination $Target -Recurse }
    }
    $Success = $true
    Write-Host 'YAC update installed. Your settings and logs have been preserved.'
} catch {
    Write-Host ('Update failed: ' + $_.Exception.Message)
    $Undo = $Changed.ToArray()
    [Array]::Reverse($Undo)
    foreach ($Name in $Undo) {
        try {
            $Target = ChildPath $Destination $Name
            $Saved = ChildPath $Backup $Name
            if (Test-Path -LiteralPath $Target) { Remove-Item -LiteralPath $Target -Recurse -Force }
            if (Test-Path -LiteralPath $Saved) { Move-Item -LiteralPath $Saved -Destination $Target }
        } catch { Write-Host ('Could not restore ' + $Name + ': ' + $_.Exception.Message) }
    }
    Write-Host ('Update recovery files are at ' + $Stage)
} finally {
    if ($Lock) { $Lock.Dispose() }
}
if ($Success) {
    # Verify the exact stage path before removing the temporary update tree.
    if ((Resolve-Path -LiteralPath $Stage).Path -eq $Stage -and $Stage -ne $Destination) {
        Remove-Item -LiteralPath $Stage -Recurse -Force -ErrorAction SilentlyContinue
    }
    Read-Host 'Press Enter to start YAC' | Out-Null
    Start-Process -FilePath (Join-Path $Destination $Program) -WorkingDirectory $Destination
} else {
    Read-Host 'Press Enter to close this updater' | Out-Null
}
'''


def run(destination, *, selected_release=None):
    import os
    import update_yac as updater
    if sys.platform != 'win32' or not getattr(sys, 'frozen', False):
        raise ValueError('Windows updates require the portable YAC executable.')
    if not sys.stdin.isatty():
        raise ValueError('Run YAC in an interactive console.')
    if selected_release is None:
        print('Checking for YAC updates over the internet...', flush=True)
        release = updater.newest_release(json.loads(updater.fetch(updater.API, 2 * 1024 * 1024)))
        marker = destination / 'release.json'
        current = json.loads(marker.read_text()) if marker.is_file() else {}
        if current.get('tag') == release['tag_name'] or current.get('published_at', '') >= release['published_at']:
            print('YAC is up to date.')
            return 0
    else:
        release = selected_release
    archive, checksum = updater.asset_pair(release, windows=True)
    while selected_release is None:
        print('A new YAC update is available. r read changes; q cancel; Space install.', flush=True)
        key = updater.read_key().casefold()
        if key in ('q', '\x03', '\x04', ''):
            print('Cancelled.')
            return 0
        if key == 'r':
            print(updater.clean_changes(release.get('body') or 'No release notes supplied.'))
        if key == ' ':
            break
    from modules.update_lock import application_lock
    with application_lock(destination, exclusive=True):
        data = updater.fetch(archive['browser_download_url'], updater.MAX_ARCHIVE)
        expected = updater.fetch(checksum['browser_download_url'], 4096).decode('ascii').split()
        if (len(expected) != 2 or expected[1].lstrip('*') != archive['name'] or
                not re.fullmatch('[a-fA-F0-9]{64}', expected[0]) or
                hashlib.sha256(data).hexdigest() != expected[0].lower()):
            raise ValueError('Download checksum failed; YAC was not changed.')
        stage = Path(tempfile.mkdtemp(prefix='yac-windows-update-')).resolve()
        handed_over = False
        try:
            source, program = extract(data, stage)
            (source / 'release.json').write_text(json.dumps({'tag': release['tag_name'],
                                                           'published_at': release['published_at']}))
            script = installer_script(destination, source, stage, program, Path(sys.executable).name, os.getpid())
            encoded = base64.b64encode(script.encode('utf-16le')).decode('ascii')
            powershell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
            subprocess.Popen([str(powershell), '-NoProfile', '-EncodedCommand', encoded],
                             creationflags=subprocess.CREATE_NEW_CONSOLE)
            handed_over = True
        finally:
            if not handed_over and stage.parent == Path(tempfile.gettempdir()).resolve():
                shutil.rmtree(stage)
    return REQUEST
