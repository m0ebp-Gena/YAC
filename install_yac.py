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
    elif not target.is_file() or source.read_bytes() != target.read_bytes():
        shutil.copyfile(source, target)


def ask(question):
    try:
        return input(question + " [y/N] ").strip().casefold() in {"y", "yes"}
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled.")
        return False


def launcher_text(destination):
    executable = shlex.quote(str(destination / ".venv/bin/python"))
    program = shlex.quote(str(destination / "yac.py"))
    return "#!/bin/sh\nexec " + executable + " " + program + ' "$@"\n'


def install_shortcut(launcher, home):
    system_directory = Path("/usr/local/bin")
    system_target = system_directory / "yac"
    # Never replace another command, including a broken symbolic link.
    if system_target.exists() or system_target.is_symlink():
        print("An existing /usr/local/bin/yac was left unchanged.")
        return
    elif system_directory.is_dir():
        writable = os.access(system_directory, os.W_OK)
        sudo = shutil.which("sudo")
        if writable or sudo:
            explanation = "" if writable else " (requires sudo; you may be asked for your password)"
            if ask("Create /usr/local/bin/yac" + explanation + "?"):
                try:
                    if writable:
                        with system_target.open("x", encoding="utf-8", newline="\n") as stream:
                            stream.write(launcher.read_text(encoding="utf-8"))
                        system_target.chmod(0o755)
                    else:
                        # Only the shortcut is installed with elevated privileges.
                        # noclobber also protects against an intervening new file.
                        command = 'set -C; umask 022; cat "$1" > "$2" && chmod 755 "$2"'
                        subprocess.run([sudo, "sh", "-c", command, "yac-launcher", str(launcher), str(system_target)], check=True)
                    print("Launcher installed. Type yac in your terminal.")
                    print("This shortcut points to your personal YAC installation.")
                    return
                except (OSError, subprocess.CalledProcessError):
                    print("Could not install the system shortcut. YAC itself is installed.")
    else:
        print("/usr/local/bin is unavailable; YAC's own launcher remains usable.")

    local_target = home / ".local/bin/yac"
    if local_target.exists() or local_target.is_symlink():
        print("An existing personal yac command was left unchanged.")
        return
    if ask("Create a personal shortcut at " + str(local_target) + " instead?"):
        local_target.parent.mkdir(parents=True, exist_ok=True)
        with local_target.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(launcher.read_text(encoding="utf-8"))
        local_target.chmod(0o755)
        print("Personal shortcut created: " + str(local_target))
        print("If ~/.local/bin is in your PATH, type yac. Otherwise use ~/yac/run-yac.")


def main(source=None, home=None):
    if sys.version_info < (3, 10):
        print("Install Python 3.10 or newer using your package manager, then try again.")
        return 1
    if sys.platform not in {"linux", "darwin"}:
        print("This installer is for Linux and macOS source packages.")
        return 1
    if os.geteuid() == 0:
        print("Run this installer as your normal user, without sudo.")
        print("It will ask separately if administrator access is needed for a shortcut.")
        return 1
    source = Path(source or __file__).resolve()
    if source.is_file():
        source = source.parent
    home = Path(home or Path.home()).resolve()
    destination = home / "yac"
    for name in ("yac.py", "modules", "lang", "rad_cmds"):
        if not (source / name).exists():
            print("Missing " + name + ". Extract the complete YAC source package, not the Windows executable package.")
            return 1
    if destination.is_symlink() or (destination.exists() and not destination.is_dir()):
        print(str(destination) + " is not a regular installation directory; left unchanged.")
        return 1
    updating = destination.exists()
    if updating and not (destination / "yac.py").is_file():
        print(str(destination) + " does not contain a YAC installation; left unchanged.")
        return 1
    print("Python " + sys.version.split()[0] + " is available.")
    print("Setup updates changed YAC files and preserves existing settings, logs and .venv.")
    print("It installs pyserial only if a compatible version is missing from the private environment.")
    if not ask(("Update " if updating else "Create ") + str(destination) + " and set up YAC?"):
        print("No installation was made.")
        return 0
    try:
        destination.mkdir(exist_ok=True)
        copy_changed(source / "yac.py", destination / "yac.py")
        for name in ("modules", "lang", "rad_cmds"):
            copy_changed(source / name, destination / name)
        if (source / 'doc/supported-radios').is_dir():
            copy_changed(source / 'doc/supported-radios', destination / 'doc/supported-radios')
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
                print("Creating the private Python environment...")
                subprocess.run([sys.executable, "-m", "venv", str(destination / ".venv")], check=True)
        except subprocess.CalledProcessError:
            print("Could not create the environment. Consult your package manager's Python venv/pip instructions.")
            print("On Debian, Ubuntu and Raspberry Pi OS, the required package is usually python3-venv.")
            print("After installing it, run: python3 -m venv ~/yac/.venv")
            print('Then run: ~/yac/.venv/bin/python -m pip install "pyserial>=3.5,<4"')
            print("Start YAC with: ~/yac/.venv/bin/python ~/yac/yac.py")
            return 1
        try:
            if updating and python.is_file():
                dependency = subprocess.run([str(python), "-c",
                    "import serial; from serial.tools import list_ports; from importlib.metadata import version; "
                    "v=tuple(int(p) for p in version('pyserial').split('.')[:2]); "
                    "raise SystemExit(0 if (3,5) <= v < (4,0) else 1)"], capture_output=True)
                ready = dependency.returncode == 0
            else:
                ready = False
            if ready:
                print("Compatible pyserial is already installed; skipping pip.")
            else:
                print("Installing pyserial...")
                subprocess.run([str(python), "-m", "pip", "install", "pyserial>=3.5,<4"], check=True)
            # Import check only; no serial ports are opened.
            subprocess.run([str(python), "-c", "import yac, serial; from serial.tools import list_ports"], cwd=destination, check=True)
        except subprocess.CalledProcessError:
            print("Dependency installation or the import check failed. Check the messages above.")
            print('To retry the dependency install: ~/yac/.venv/bin/python -m pip install "pyserial>=3.5,<4"')
            print("To run YAC afterwards: ~/yac/.venv/bin/python ~/yac/yac.py")
            return 1
        launcher = destination / "run-yac"
        text = launcher_text(destination)
        if launcher.is_symlink():
            raise OSError("Refusing to overwrite symbolic link: " + str(launcher))
        if not launcher.is_file() or launcher.read_text(encoding="utf-8") != text:
            launcher.write_text(text, encoding="utf-8", newline="\n")
        launcher.chmod(0o755)
        print("YAC is installed. Start it in your terminal with: ~/yac/run-yac")
        install_shortcut(launcher, home)
        print("Settings and logs stay in " + str(destination))
        print("Setup has not opened any radio ports or started YAC.")
        return 0
    except OSError as error:
        print("Setup failed: " + str(error))
        print("Any files already created were left in " + str(destination))
        return 1


if __name__ == "__main__":
    sys.exit(main())
