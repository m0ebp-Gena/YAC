"""Ask for and save the user's preferred name or callsign."""

from __future__ import annotations

import os
import re
import sys
import tempfile
from pathlib import Path


MAX_CALL_LENGTH = 10


def _read_label(root: Path, language: str, label_id: str, fallback: str) -> str:
    try:
        return (root / "lang" / language / "labels" / label_id).read_text(
            encoding="utf-8-sig"
        ).strip()
    except OSError:
        return fallback


def _save_call(ini_path: Path, call: str) -> None:
    """Set [yac] call= while preserving radio profiles and other INI content."""
    contents = ini_path.read_text(encoding="utf-8-sig") if ini_path.exists() else ""
    newline = "\r\n" if "\r\n" in contents else "\n"
    lines = contents.splitlines(keepends=True)
    section_start: int | None = None
    section_end = len(lines)
    call_line: int | None = None

    for index, line in enumerate(lines):
        body = line.rstrip("\r\n")
        header = re.match(r"^[ \t]*\[([^\]]+)\]", body)
        if header:
            if section_start is not None:
                section_end = index
                break
            if header.group(1).strip().casefold() == "yac":
                section_start = index
                continue
        if section_start is not None and re.match(
            r"^[ \t]*call[ \t]*=", body, re.IGNORECASE
        ):
            call_line = index

    if section_start is None:
        if lines and not lines[-1].endswith(("\n", "\r")):
            lines[-1] += newline
        if lines and lines[-1].strip():
            lines.append(newline)
        lines.extend((f"[yac]{newline}", f"call={call}{newline}"))
    elif call_line is not None:
        old_line = lines[call_line]
        ending = "\r\n" if old_line.endswith("\r\n") else "\n" if old_line.endswith("\n") else ""
        prefix = re.match(r"^([ \t]*call[ \t]*=[ \t]*)", old_line, re.IGNORECASE)
        lines[call_line] = f"{prefix.group(1)}{call}{ending}"
    else:
        insertion = section_end
        while insertion > section_start + 1 and not lines[insertion - 1].strip():
            insertion -= 1
        lines.insert(insertion, f"call={call}{newline}")

    ini_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="", dir=ini_path.parent,
            prefix=f".{ini_path.name}.", suffix=".tmp", delete=False,
        ) as temporary_file:
            temporary_file.write("".join(lines))
            temporary_path = Path(temporary_file.name)
        os.replace(temporary_path, ini_path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def _draw_input(buffer: list[str], cursor: int, previous_length: int) -> int:
    """Redraw the short editable input and leave the cursor at its position."""
    value = "".join(buffer)
    width = max(previous_length, len(buffer))
    sys.stdout.write("\r" + " " * width + "\r" + value)
    if len(buffer) > cursor:
        sys.stdout.write("\b" * (len(buffer) - cursor))
    sys.stdout.flush()
    return len(buffer)


def _read_edit_key() -> str:
    if os.name == "nt":
        import msvcrt

        key = msvcrt.getwch()
        if key in ("\x00", "\xe0"):
            return {
                "K": "left", "M": "right", "G": "home", "O": "end", "S": "delete",
            }.get(msvcrt.getwch(), "")
        if key in ("\r", "\n"):
            return "enter"
        if key in ("\b", "\x7f"):
            return "backspace"
        if key == "\x03":
            raise KeyboardInterrupt
        return key

    import select

    key = sys.stdin.read(1)
    if key in ("\r", "\n"):
        return "enter"
    if key in ("\x7f", "\x08"):
        return "backspace"
    if key == "\x03":
        raise KeyboardInterrupt
    if key != "\x1b":
        return key

    sequence = ""
    for _ in range(3):
        if not select.select([sys.stdin], [], [], 0.05)[0]:
            break
        sequence += sys.stdin.read(1)
    return {
        "[D": "left", "[C": "right", "[H": "home", "[F": "end",
        "[3~": "delete", "OH": "home", "OF": "end",
    }.get(sequence, "")


def _edit_line(initial: str = "") -> str:
    """Read one echoed line with insertion, deletion, and cursor movement."""
    if os.name != "nt":
        if not sys.stdin.isatty():
            raise RuntimeError("Name entry requires an interactive terminal.")
        import termios
        import tty

        descriptor = sys.stdin.fileno()
        previous_settings = termios.tcgetattr(descriptor)
        tty.setraw(descriptor)
    else:
        previous_settings = None

    buffer = list(initial[:MAX_CALL_LENGTH])
    cursor = len(buffer)
    drawn_length = _draw_input(buffer, cursor, 0)
    try:
        while True:
            key = _read_edit_key()
            if key == "enter":
                sys.stdout.write("\n")
                sys.stdout.flush()
                return "".join(buffer)
            if key == "left":
                cursor = max(0, cursor - 1)
            elif key == "right":
                cursor = min(len(buffer), cursor + 1)
            elif key == "home":
                cursor = 0
            elif key == "end":
                cursor = len(buffer)
            elif key == "backspace":
                if cursor:
                    del buffer[cursor - 1]
                    cursor -= 1
            elif key == "delete":
                if cursor < len(buffer):
                    del buffer[cursor]
            elif len(key) == 1 and key.isprintable():
                if len(buffer) < MAX_CALL_LENGTH:
                    buffer.insert(cursor, key)
                    cursor += 1
                else:
                    sys.stdout.write("\a")
            drawn_length = _draw_input(buffer, cursor, drawn_length)
    finally:
        if previous_settings is not None:
            termios.tcsetattr(descriptor, termios.TCSADRAIN, previous_settings)


def collect_name(
    root: Path, ini_path: Path, language: str, *, initial: str = ""
) -> str:
    """Collect a name/callsign of at most 10 characters and save it to yac.ini."""
    from modules import lang_sel

    prompt = _read_label(root, language, "l004", "What should the program call you?")
    instruction = _read_label(
        root, language, "l006", "Enter your callsign or name. Maximum 10 characters."
    )
    confirmation = _read_label(
        root, language, "l007", "Press Space to confirm or E to edit your input."
    )

    name = initial[:MAX_CALL_LENGTH]
    while True:
        print(prompt)
        print(instruction)
        name = _edit_line(name).strip()
        if not name:
            continue

        print(name)
        print(confirmation)
        while True:
            key = lang_sel.read_key()
            if key == " ":
                _save_call(ini_path, name)
                os.system("cls" if os.name == "nt" else "clear")
                return name
            # Accept both the label's E instruction and N used in the module rules.
            if key.casefold() in {"e", "n"}:
                print()
                break
