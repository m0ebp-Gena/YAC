"""Compare macOS terminal input modes without starting YAC or a radio.

Run: python3 -m tests.hardware.braille_input_check
Use the same braille table and display for all three stages.
"""

from __future__ import annotations

import os
import select
import sys
import time
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path


class LoggedOutput:
    """Show diagnostic output in Terminal and save it immediately to a file."""

    def __init__(self, terminal, log):
        self.terminal = terminal
        self.log = log

    def write(self, text: str) -> int:
        self.terminal.write(text)
        self.log.write(text)
        self.flush()
        return len(text)

    def flush(self) -> None:
        self.terminal.flush()
        self.log.flush()


def run_logged() -> int:
    log_path = Path(__file__).resolve().with_name("braille-input-check.log")
    with log_path.open("a", encoding="utf-8") as log:
        with redirect_stdout(LoggedOutput(sys.stdout, log)):
            print(f"\n--- Braille input check: {datetime.now().astimezone().isoformat()} ---")
            print(f"Results are also saved to {log_path}")
            try:
                return main()
            except KeyboardInterrupt:
                print("\nStopped; terminal settings restored.")
                return 130


def check_mode(mode: str, seconds: float = 20) -> None:
    import termios
    import tty

    descriptor = sys.stdin.fileno()
    previous = termios.tcgetattr(descriptor)
    print(f"\n{mode}: type abc, then Space and Enter. This stage lasts {seconds:g} seconds.", flush=True)
    try:
        if mode == "raw":
            tty.setraw(descriptor)
        else:
            tty.setcbreak(descriptor)
        deadline = time.monotonic() + seconds
        received = False
        while time.monotonic() < deadline:
            if not select.select([descriptor], [], [], max(0, deadline - time.monotonic()))[0]:
                break
            data = os.read(descriptor, 4096)
            if not data:
                break
            received = True
            if b"\x03" in data:
                raise KeyboardInterrupt
            # Explicit CR/LF keeps output readable even when raw mode disables ONLCR.
            sys.stdout.write(f"\r\nReceived bytes: {data!r}; UTF-8 text: {data.decode('utf-8', errors='replace')!r}\r\n")
            sys.stdout.flush()
    finally:
        termios.tcsetattr(descriptor, termios.TCSADRAIN, previous)
    if not received:
        print("No input bytes received.")


def main() -> int:
    if sys.platform != "darwin":
        print("Run this diagnostic in Terminal on the Mac being tested.")
        return 1
    if not sys.stdin.isatty():
        print("This diagnostic requires an interactive terminal.")
        return 1
    print("Braille input check. Ctrl+C stops the test and restores terminal settings.")
    print("First, ordinary line input: type abc, then Space and Enter.")
    value = input("Text: ")
    print(f"Python received: {value!r}")
    check_mode("raw")
    check_mode("cbreak")
    print("\nDone. Repeat with the other display and compare results.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_logged())
