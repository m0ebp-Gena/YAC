"""Load and display the currently selected language's help text."""

from __future__ import annotations

from pathlib import Path


def get_help(root: Path, language: str, help_id: str = "h001") -> str:
    """Return a help document from the active language folder."""
    help_path = root / "lang" / language / "help" / help_id
    try:
        return help_path.read_text(encoding="utf-8-sig").strip()
    except OSError:
        return "Help is not available in the selected language."
