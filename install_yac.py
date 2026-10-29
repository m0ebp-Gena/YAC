"""Interactive source installer for Linux and macOS. Run as a normal user."""
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys


def copy_changed(source, target):
    """Merge shipped files, preserving identical files and unrelated user data."""
    if target.is_symlink():
        raise OSError("Refusing to overwrite symbolic link: " + str(target))
    if source.is_dir():
        target.mkdir(parents=True, exist_ok=True)
        for item in source.iterdir():
            if item.name == "__pycache__" or item.suffix in {".pyc", ".zip"}:
                continue
            copy_changed(item, target / item.name)
    else:
        template = source.name.endswith('-template.txt')
        if not target.is_file() or source.read_bytes() != target.read_bytes():
            if template and target.exists():
                target.chmod(0o644)
            try:
                shutil.copyfile(source, target)
            finally:
                if template and target.exists():
                    target.chmod(0o444)
        elif template:
            target.chmod(0o444)


def ask(question):
    try:
        return input(question + " [Y/n] ").strip().casefold() in {"", "y", "yes"}
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled.")
        return False


def launcher_text(destination):
    executable = shlex.quote(str(destination / ".venv/bin/python"))
    program = shlex.quote(str(destination / "yac.py"))
    return "#!/bin/sh\nexec " + executable + " " + program + ' "$@"\n'


def install_shortcut(launcher, home, command_name="yac"):
    """Offer one launcher question; keep existing files without prompting."""
    if command_name not in {"yac", "update-yac"}:
        raise ValueError("Unexpected launcher name")
    system_directory = Path("/usr/local/bin")
    system_target = system_directory / command_name
    local_target = home / ".local/bin" / command_name
    if system_target.exists() or system_target.is_symlink():
        return None
    if local_target.exists() or local_target.is_symlink():
        return None
    question = "Create YAC launcher?" if command_name == "yac" else "Create update launcher?"
    if not ask(question):
        return None
    writable = system_directory.is_dir() and os.access(system_directory, os.W_OK)
    sudo = shutil.which("sudo") if system_directory.is_dir() else None
    try:
        if writable:
            with system_target.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(launcher.read_text(encoding="utf-8"))
            system_target.chmod(0o755)
            return system_target
        if sudo:
            command = 'set -C; umask 022; cat "$1" > "$2" && chmod 755 "$2"'
            subprocess.run([sudo, "sh", "-c", command, "yac-launcher", str(launcher), str(system_target)], check=True)
            return system_target
        local_target.parent.mkdir(parents=True, exist_ok=True)
        with local_target.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(launcher.read_text(encoding="utf-8"))
        local_target.chmod(0o755)
        return local_target
    except (OSError, subprocess.CalledProcessError):
        print("Launcher creation failed. Use the installed launcher directly.")
        return None


def installation_directory(home, platform):
    """Keep application files in the platform-specific personal directory."""
    return Path(home) / ("Applications" if platform == "darwin" else ".local") / "yac"


def main(source=None, home=None, update=False, pi=False):
    if sys.version_info < (3, 10):
        print("Install Python 3.10 or newer using your package manager, then try again.")
        return 1
    if sys.platform not in {"linux", "darwin"}:
        print("This installer is for the Mac/Linux package.")
        return 1
    if os.geteuid() == 0:
        print("Run this installer as your normal user, without sudo.")
        return 1
    source = Path(source or __file__).resolve()
    if source.is_file():
        source = source.parent
    home = Path(home or Path.home()).resolve()
    destination = installation_directory(home, sys.platform)
    for name in ("yac.py", "modules", "lang", "rad_cmds"):
        if not (source / name).exists():
            print("Missing " + name + ". Extract the complete YAC Mac/Linux package.")
            return 1
    if destination.is_symlink() or (destination.exists() and not destination.is_dir()):
        print(str(destination) + " is not a regular installation directory; left unchanged.")
        return 1
    updating = destination.exists()
    if updating and not (destination / "yac.py").is_file():
        print(str(destination) + " does not contain a YAC installation; left unchanged.")
        return 1
    if not update and not ask("Install YAC?"):
        print("Cancelled.")
        return 2 if pi else 0
    print("Your existing Python environments are unchanged.")
    print("Installing...", flush=True)
    try:
        destination.mkdir(parents=True, exist_ok=True)
        copy_changed(source / "yac.py", destination / "yac.py")
        for name in ("modules", "lang", "rad_cmds"):
            copy_changed(source / name, destination / name)
        if (source / 'doc/supported-radios').is_dir():
            copy_changed(source / 'doc/supported-radios', destination / 'doc/supported-radios')
        for directory in ('English', 'Deutsch', 'Espanol', 'Polski'):
            if (source / 'doc' / directory).is_dir():
                copy_changed(source / 'doc' / directory, destination / 'doc' / directory)
        for guide in (source / 'doc').glob('*'):
            if guide.is_file() and (guide.suffix in {'.md', '.html'} or guide.name in {'swr-controls.txt', 'speech-processor.txt'} or (guide.name.startswith('in-this-release-') and guide.suffix == '.txt')):
                (destination / 'doc').mkdir(parents=True, exist_ok=True)
                copy_changed(guide, destination / 'doc' / guide.name)
        if (source / "doc/linux-macos-setup.txt").is_file():
            copy_changed(source / "doc/linux-macos-setup.txt", destination / "LINUX-MACOS-SETUP.txt")
        for chart in ("KEY-BINDINGS-English.txt", "TASTENBELEGUNG-Deutsch.txt",
                      "SKROTY-KLAWISZOWE-Polski.txt", "TECLAS-Espanol.txt"):
            if (source / chart).is_file():
                copy_changed(source / chart, destination / chart)
        if not (destination / "yac.ini").exists():
            (destination / "yac.ini").write_text("[yac]\nplatform=\nlang=\ncall=\ndebug=true\n", encoding="utf-8")
        python = destination / ".venv/bin/python"
        try:
            if not python.is_file():
                print("Preparing Python...", flush=True)
                subprocess.run([sys.executable, "-m", "venv", str(destination / ".venv")], check=True, capture_output=True)
        except subprocess.CalledProcessError:
            print("Python environment setup failed.")
            print("Install Python venv/pip support (usually python3-venv), then run this installer again.")
            return 1
        try:
            if sys.platform == 'darwin':
                # The bundle ships with YAC: no HTTPS download is needed to
                # repair Python installations without configured root trust.
                subprocess.run([str(python), '-c',
                    'from modules.update_certificates import context; context()'],
                    cwd=destination, check=True, capture_output=True)
            if updating and python.is_file():
                dependency = subprocess.run([str(python), "-c",
                    "import serial; from serial.tools import list_ports; from importlib.metadata import version; "
                    "v=tuple(int(p) for p in version('pyserial').split('.')[:2]); "
                    "raise SystemExit(0 if (3,5) <= v < (4,0) else 1)"], capture_output=True)
                ready = dependency.returncode == 0
            else:
                ready = False
            if not ready:
                print("Installing dependencies...", flush=True)
                subprocess.run([str(python), "-m", "pip", "install", "pyserial>=3.5,<4"], check=True, capture_output=True)
            # Import check only; no serial ports are opened.
            subprocess.run([str(python), "-c", "import yac, serial; from serial.tools import list_ports"], cwd=destination, check=True, capture_output=True)
        except subprocess.CalledProcessError:
            print("Dependency setup failed.")
            print("To retry, check your internet connection and run this installer again.")
            return 1
        for name in ("LICENSE", "COPYING", "changelog.txt", "update_yac.py", "yac.ini.example", "error-codes.txt"):
            if (source / name).is_file():
                copy_changed(source / name, destination / name)
        launcher = destination / "run-yac"
        text = launcher_text(destination)
        if launcher.is_symlink():
            raise OSError("Refusing to overwrite symbolic link: " + str(launcher))
        if not launcher.is_file() or launcher.read_text(encoding="utf-8") != text:
            launcher.write_text(text, encoding="utf-8", newline="\n")
        launcher.chmod(0o755)
        shortcut = None
        if pi:
            print("Password: radio, unless changed.")
        if not update:
            shortcut = install_shortcut(launcher, home)
        if (destination / 'update_yac.py').is_file():
            updater = destination / 'update-yac'
            if updater.is_symlink():
                raise OSError('Refusing to overwrite symbolic link: ' + str(updater))
            updater.write_text('#!/bin/sh\nexec ' + shlex.quote(str(python)) + ' ' +
                               shlex.quote(str(destination / 'update_yac.py')) + ' "$@"\n', encoding='utf-8', newline='\n')
            updater.chmod(0o755)
            if not update:
                install_shortcut(updater, home, command_name='update-yac')
        if (source / 'release.json').is_file():
            copy_changed(source / 'release.json', destination / 'release.json')
        if not pi:
            print("Installation Complete")
            if shortcut and (str(shortcut).startswith('/usr/local/bin/') or str(shortcut.parent) in os.environ.get('PATH', '').split(os.pathsep)):
                print("Type yac to start.")
            else:
                print("Start: " + shlex.quote(str(launcher)))
        return 0
    except OSError as error:
        print("Setup failed: " + str(error))
        print("Any files already created were left in " + str(destination))
        return 1


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--update', action='store_true', help='Update after confirmation by update-yac')
    parser.add_argument('--pi', action='store_true', help='Pi wrapper completes helper installation')
    args = parser.parse_args()
    sys.exit(main(update=args.update, pi=args.pi))
