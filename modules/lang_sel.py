"""Select YAC's language and save it in the project-level yac.ini.

This module belongs in the project's modules/ directory. It reads the
language names and confirmation prompt from lang/<code>/labels, then edits
only the lang setting in the yac.ini one directory above modules/.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import tempfile
from pathlib import Path
from modules.ini_settings import IniError


LANGUAGE_CODES = ("en", "de", "pl", "es")


def project_root() -> Path:
    """Return the YAC root when this file is stored in modules/."""
    module_directory = Path(__file__).resolve().parent
    if module_directory.name.casefold() == "modules":
        return module_directory.parent
    return module_directory


def read_label(root: Path, language: str, label_id: str) -> str:
    label_path = root / "lang" / language / "labels" / label_id
    return label_path.read_text(encoding="utf-8-sig").strip()


def set_language(ini_path: Path, language: str) -> None:
    from modules.ini_settings import save_error
    try:
        _write_language(ini_path, language)
    except (OSError, UnicodeError) as error:
        save_error(ini_path, error)


def _write_language(ini_path: Path, language: str) -> None:
    """Update [yac] lang= while preserving all other INI content."""
    if ini_path.exists():
        with ini_path.open("r", encoding="utf-8-sig", newline="") as ini_file:
            contents = ini_file.read()
    else:
        contents = ""

    newline = "\r\n" if "\r\n" in contents else "\n"
    lines = contents.splitlines(keepends=True)
    section_start = None
    section_end = len(lines)
    language_line = None

    for index, line in enumerate(lines):
        body = line.rstrip("\r\n")
        header = re.match(r"^\s*\[([^\]]+)\]\s*(?:[;#].*)?$", body)
        if header:
            if section_start is not None:
                section_end = index
                break
            if header.group(1).strip().casefold() == "yac":
                section_start = index
                continue

        if section_start is not None and re.match(r"^\s*lang\s*=", body, re.IGNORECASE):
            language_line = index

    if section_start is None:
        if contents and not contents.endswith(("\n", "\r")):
            lines[-1] += newline
        lines.extend(("[yac]" + newline, f"lang={language}" + newline))
    elif language_line is not None:
        old_line = lines[language_line]
        ending = "\r\n" if old_line.endswith("\r\n") else "\n" if old_line.endswith("\n") else ""
        # Do not use \s here: old_line still includes its newline, and \s
        # would absorb that newline when replacing an empty lang= value.
        prefix = re.match(r"^([ \t]*lang[ \t]*=[ \t]*)", old_line, re.IGNORECASE).group(1)
        lines[language_line] = f"{prefix}{language}{ending}"
    else:
        insert_at = section_end
        while insert_at > section_start + 1 and not lines[insert_at - 1].strip():
            insert_at -= 1
        lines.insert(insert_at, f"lang={language}{newline}")

    ini_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="", dir=ini_path.parent,
            prefix=f".{ini_path.name}.", suffix=".tmp", delete=False
        ) as temporary_file:
            updated_contents = "".join(lines).rstrip("\r\n") + newline
            temporary_file.write(updated_contents)
            temporary_path = Path(temporary_file.name)
        os.replace(temporary_path, ini_path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def read_key(idle_callback=None) -> str:
    """Read one key without requiring Enter, restoring terminal state afterward."""
    if os.name == "nt":
        import msvcrt
        if idle_callback is not None:
            import time
            while not msvcrt.kbhit():
                idle_callback()
                time.sleep(0.1)

        key = msvcrt.getwch()
        if key in ("\x00", "\xe0"):
            msvcrt.getwch()  # Consume the second byte of an extended key.
            return ""
        return key

    import termios
    import tty

    descriptor = sys.stdin.fileno()
    if not sys.stdin.isatty():
        raise RuntimeError("YAC language selection requires an interactive terminal.")
    previous_settings = termios.tcgetattr(descriptor)
    try:
        # The default TCSAFLUSH discards presses queued while a radio command
        # was running. Keep them for the next read instead.
        tty.setraw(descriptor, termios.TCSANOW)
        if idle_callback is not None:
            import select
            # Idle callbacks may print status. Preserve terminal output newline
            # processing while retaining raw, single-key input.
            raw_settings = termios.tcgetattr(descriptor)
            raw_settings[1] = previous_settings[1]
            termios.tcsetattr(descriptor, termios.TCSANOW, raw_settings)
            while not select.select([descriptor], [], [], 0.1)[0]:
                idle_callback()
        return sys.stdin.read(1)
    finally:
        termios.tcsetattr(descriptor, termios.TCSADRAIN, previous_settings)


def show_language_menu(root: Path) -> str | None:
    """Show native language names and confirm the selected language."""
    names = {}
    prompts = {}
    confirmations = {}
    for code in LANGUAGE_CODES:
        names[code] = read_label(root, code, "l000")
        prompts[code] = read_label(root, code, "l002")
        confirmations[code] = read_label(root, code, "l007")

    choices = {str(number): code for number, code in enumerate(LANGUAGE_CODES, start=1)}
    while True:
        for number, code in enumerate(LANGUAGE_CODES, start=1):
            print(f"{number} {prompts[code]} {names[code]}",
                  end="" if number == len(LANGUAGE_CODES) else "\n", flush=True)
        while True:
            key = read_key()
            if key.casefold() == "q" or key in ("\x03", "\x04"):
                return None
            if key in choices:
                selected = choices[key]
                print()
                # Keep the prompt under the terminal cursor, matching the main
                # interface's speech/braille feedback. Flush before raw input.
                print(f"{names[selected]}: {confirmations[selected]}", end="", flush=True)
                while True:
                    confirm_key = read_key()
                    if confirm_key.casefold() == "y":
                        print(flush=True)
                        return selected
                    if confirm_key.casefold() == "n":
                        print(flush=True)
                        break
                    if confirm_key.casefold() == "q" or confirm_key in ("\x03", "\x04"):
                        return None
                break


def clear_console() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def main() -> int:
    parser = argparse.ArgumentParser(description="Choose YAC's language.")
    parser.add_argument(
        "ini_file", nargs="?", type=Path,
        help="INI file to update (defaults to yac.ini in the YAC root)",
    )
    args = parser.parse_args()
    root = project_root()
    ini_path = (args.ini_file or root / "yac.ini").expanduser().resolve()

    try:
        for code in LANGUAGE_CODES:
            read_label(root, code, "l000")
            read_label(root, code, "l002")
            read_label(root, code, "l025")
            read_label(root, code, "l007")
    except OSError as error:
        print(f"Could not read YAC language labels: {error}", file=sys.stderr)
        return 1

    while True:
        try:
            selected = show_language_menu(root)
        except RuntimeError as error:
            print(error, file=sys.stderr)
            return 1
        if selected is None:
            clear_console()
            raise SystemExit(0)
        try:
            set_language(ini_path, selected)
        except (OSError, IniError):
            print(read_label(root, selected, "l025"), file=sys.stderr)
            return 1
        clear_console()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
