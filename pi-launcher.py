#!/usr/bin/env python3
"""Raspberry Pi console entry point for YAC. SPDX-License-Identifier: GPL-3.0-only."""

import configparser
import os
from pathlib import Path
import shutil
import subprocess
import sys
import pi_audio


def wait_for_boot():
    """Wait for boot jobs before restoring speech or asking for YAC input."""
    result = subprocess.run(
        ['/usr/bin/systemctl', 'is-system-running', '--wait'],
        capture_output=True, text=True, timeout=90,
    )
    # An unrelated failed unit must not prevent console use after boot finishes.
    if result.stdout.strip() not in {'running', 'degraded'}:
        raise RuntimeError('Boot did not finish within the startup wait.')


def play_cw(message):
    """Finish a short ALSA cue before returning or requesting poweroff."""
    source = Path.home() / ".local/share/cw" / message
    if not source.is_file():
        print(f"CW cue not found: {source}")
        return
    try:
        result = subprocess.run(
            ["/usr/bin/cw", "-s", "alsa", "-w", "15", "-t", "950",
             "-v", "60", "-f", str(source)],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode:
            print(f"Could not play CW {message}: {result.stderr.strip()}")
    except (OSError, subprocess.TimeoutExpired) as error:
        print(f"Could not play CW {message}: {error}")


def main():
    if sys.platform != "linux":
        print("This launcher is for the Raspberry Pi Linux image.")
        return 1
    try:
        wait_for_boot()
    except (OSError, RuntimeError, subprocess.SubprocessError, KeyboardInterrupt) as error:
        try:
            pi_audio.helper('ready')
        except (OSError, RuntimeError, subprocess.SubprocessError):
            pass  # Independent boot recovery remains armed.
        print(f'Boot wait stopped: {error}. Returning to the console.')
        return 1
    config = configparser.ConfigParser(interpolation=None)
    settings_file = Path.home() / ".config/yac/pi-launcher.ini"
    try:
        config.read(settings_file, encoding="utf-8")
        settings = config["launcher"] if config.has_section("launcher") else {}
        mode = settings.get("access_mode", "both").strip()
        volume = int(settings.get("volume", "70"))
        if mode not in {"both", "braille", "speech"} or not 0 <= volume <= 100:
            raise ValueError("access_mode must be both/braille/speech; volume must be 0..100")
        command = Path(settings.get("yac_command", "~/.local/yac/run-yac")).expanduser()
        card = settings.get("alsa_card", "default").strip()
        control = settings.get("alsa_control", "").strip()
    except (OSError, configparser.Error, ValueError) as error:
        try:
            pi_audio.helper('ready')
        except Exception:
            pass  # The boot recovery timer is the independent fallback.
        print(f"Cannot read {settings_file}: {error}")
        return 1
    try:
        # Restore console speech before audio setup or any startup error message.
        # Braille-only startup cancels recovery without enabling speech.
        pi_audio.helper('ready-braille' if mode == 'braille' else 'ready')
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        print(f'Could not finish boot speech setup: {error}. Returning to the console.')
        return 1
    if not command.is_file():
        print(f"YAC launcher not found: {command}. Install YAC or set yac_command.")
        return 1

    try:
        if not pi_audio.setup(config, settings_file, force='--audio-setup' in sys.argv[1:]):
            return 0
        if mode != 'braille':
            pi_audio.helper('complete')
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, EOFError) as error:
        print(f'Audio setup failed: {error}. Returning to the console.')
        return 1
    except KeyboardInterrupt:
        print('\nAudio setup cancelled. Returning to the console.')
        return 130

    # Do not guess an audio device or modify ALSA in braille-only mode.
    # access_mode currently governs audio preparation only, not BRLTTY preferences.
    if mode != "braille" and control:
        mixer = shutil.which("amixer")
        if mixer:
            result = subprocess.run(
                [mixer, "-c", card, "sset", control, f"{volume}%", "unmute"],
                capture_output=True, text=True,
            )
            if result.returncode:
                print("Could not set startup audio; continuing with current audio settings.")
                print(result.stderr.strip())
        else:
            print("amixer is unavailable; keeping current audio settings.")
    try:
        environment = dict(os.environ, YAC_PI_IMAGE='1')
        result = subprocess.run([str(command)], cwd=command.parent, env=environment)
    except OSError as error:
        print(f"Could not start YAC: {error}")
        return 1
    except KeyboardInterrupt:
        print("\nLauncher interrupted. Returning to the console.")
        return 130
    if result.returncode:
        print(f"YAC stopped with status {result.returncode}. Returning to the console.")
        return 1

    # Temporary closing prompt until YAC owns appliance-mode confirmation.
    while True:
        try:
            answer = input("Shut down the Pi? Y/N: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nReturning to the console.")
            return 0
        if answer == "n":
            play_cw("k")
            return 0
        if answer == "y":
            play_cw("73")
            result = subprocess.run(["sudo", "-n", "systemctl", "poweroff"])
            if result.returncode:
                print("Shutdown failed. Returning to the console; check shutdown permission.")
            return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
