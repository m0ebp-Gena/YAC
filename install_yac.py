"""Interactive source installer for Linux and macOS. Run as a normal user."""
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys


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
    if destination.exists() or destination.is_symlink():
        print(str(destination) + " already exists and has been left unchanged.")
        print("If YAC is installed there, run ~/yac/run-yac.")
        print("For a fresh installation, move the existing folder somewhere safe and run this installer again.")
        return 1
    print("Python " + sys.version.split()[0] + " is available.")
    print("Setup creates ~/yac, copies YAC's source and data, and creates a private .venv.")
    print("It downloads pyserial using pip. Your operating system's Python packages are unchanged.")
    if not ask("Create " + str(destination) + " and set up YAC?"):
        print("No installation was made.")
        return 0
    try:
        destination.mkdir()
        shutil.copyfile(source / "yac.py", destination / "yac.py")
        for name in ("modules", "lang", "rad_cmds"):
            shutil.copytree(source / name, destination / name,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.zip"))
        if (source / "doc/linux-macos-setup.txt").is_file():
            shutil.copyfile(source / "doc/linux-macos-setup.txt", destination / "LINUX-MACOS-SETUP.txt")
        for chart in ("KEY-BINDINGS-English.txt", "TASTENBELEGUNG-Deutsch.txt",
                      "SKROTY-KLAWISZOWE-Polski.txt", "TECLAS-Espanol.txt"):
            if (source / chart).is_file():
                shutil.copyfile(source / chart, destination / chart)
        (destination / "yac.ini").write_text("[yac]\nplatform=\nlang=\ncall=\ndebug=true\n", encoding="utf-8")
        print("Creating the private Python environment...")
        try:
            subprocess.run([sys.executable, "-m", "venv", str(destination / ".venv")], check=True)
        except subprocess.CalledProcessError:
            print("Could not create the environment. Consult your package manager's Python venv/pip instructions.")
            print("On Debian, Ubuntu and Raspberry Pi OS, the required package is usually python3-venv.")
            print("After installing it, run: python3 -m venv ~/yac/.venv")
            print('Then run: ~/yac/.venv/bin/python -m pip install "pyserial>=3.5,<4"')
            print("Start YAC with: ~/yac/.venv/bin/python ~/yac/yac.py")
            return 1
        python = destination / ".venv/bin/python"
        print("Installing pyserial...")
        try:
            subprocess.run([str(python), "-m", "pip", "install", "pyserial>=3.5,<4"], check=True)
            # Import check only; no serial ports are opened.
            subprocess.run([str(python), "-c", "import yac, serial; from serial.tools import list_ports"], cwd=destination, check=True)
        except subprocess.CalledProcessError:
            print("Dependency installation or the import check failed. Check the messages above.")
            print('To retry the dependency install: ~/yac/.venv/bin/python -m pip install "pyserial>=3.5,<4"')
            print("To run YAC afterwards: ~/yac/.venv/bin/python ~/yac/yac.py")
            return 1
        launcher = destination / "run-yac"
        launcher.write_text(launcher_text(destination), encoding="utf-8", newline="\n")
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
