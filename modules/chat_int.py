"""Display compact YAC responses for speech and braille.

This module owns presentation only. Key bindings, terminal input, and radio
commands are orchestrated by yac.py.
"""

from __future__ import annotations

import sys
from pathlib import Path


_response_open = False


def finish_response() -> None:
    """Advance only when needed, keeping a response under the cursor until then."""
    global _response_open
    if _response_open:
        sys.stdout.write("\n")
        _response_open = False


def label(root: Path, language: str, key: str, fallback: str = "") -> str:
    """Read one localized label, using the supplied fallback if unavailable."""
    try:
        return (root / "lang" / language / "labels" / key).read_text(
            encoding="utf-8-sig"
        ).strip()
    except OSError:
        return fallback


def show_prompt(call: str) -> None:
    global _response_open
    _response_open = False


def show_request(call: str, request: str, *, prompt_open: bool = False) -> None:
    """Command keys are deliberately silent; responses start their own lines."""


def show_frequency_prompt(root: Path, language: str) -> None:
    finish_response()
    sys.stdout.write(label(root, language, "l033", "New Freq") + " ")
    sys.stdout.flush()


def show_step_size_prompt(root: Path, language: str, mode: str) -> None:
    prompt = label(root, language, "l069", "Step Size {mode}?")
    finish_response()
    sys.stdout.write(prompt.format(mode=mode) + " ")
    sys.stdout.flush()


def show_response(response: str) -> None:
    global _response_open
    if response:
        # Keep the terminal cursor on the response so cursor-following braille
        # displays leave that response under the user's fingertips. The next
        # request starts a new transcript line after its key has been read.
        finish_response()
        sys.stdout.write(response)
        sys.stdout.flush()
        _response_open = True


def show_goodbye(root: Path, language: str, call: str = "") -> None:
    finish_response()
    goodbye = label(root, language, "l032", "Bye")
    print(f"{goodbye} {call.strip()}".rstrip())



def show_back(root: Path, language: str) -> None:
    show_response(label(root, language, "l207", "Top Level"))


def show_done(root: Path, language: str) -> None:
    show_response(label(root, language, "l354", "Done"))
