"""Load and display the currently selected language's help text."""

from __future__ import annotations

from pathlib import Path
import shutil
import textwrap

from modules import chat_int


def get_help(root: Path, language: str, help_id: str = "h001") -> str:
    """Return a help document from the active language folder."""
    help_path = root / "lang" / language / "help" / help_id
    try:
        return help_path.read_text(encoding="utf-8-sig").strip()
    except OSError:
        return "Help is not available in the selected language."


def show_paged(root, language, text, read_key, *, page_lines=None, columns=None):
    """Short text returns directly; Space advances long text and q leaves it."""
    size = shutil.get_terminal_size((80, 24))
    width = max(1, columns or size.columns)
    height = max(1, page_lines or size.lines - 4)
    lines = []
    for line in text.expandtabs(4).splitlines():
        lines.extend(textwrap.wrap(line, width=width, replace_whitespace=False) or [''])
    if not lines:
        chat_int.show_response(chat_int.label(root, language, 'l363'))
        return
    for start in range(0, len(lines), height):
        chat_int.show_response('\n'.join(lines[start:start + height]))
        if start + height < len(lines):
            chat_int.show_response(chat_int.label(root, language, 'l362'))
            while True:
                key = read_key().casefold()
                if key in {'q', '\x03', '\x04'}:
                    return
                if key == ' ':
                    break
