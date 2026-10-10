# YAC 001 beta — Windows 64-bit

Release date: 10 October 2026

This first Windows beta provides a keyboard-operated radio interface designed
with speech and braille access in mind. Python and pyserial are bundled;
testers do not need to install Python.

## Download and start

Download **YAC-001-beta-2026-10-10.zip** from the release assets. Use Windows
**Extract All** to unpack the entire ZIP into a writable folder such as
Downloads or Documents. Open the extracted folder and run **YAC-001-beta.exe**.
Keep the executable, `_internal`, `lang` and `rad_cmds` together.

Read **START-HERE-English.txt**, **HIER-STARTEN-Deutsch.txt** or
**ZACZNIJ-TUTAJ-Polski.txt** before using the controls. Connect your radio,
install its manufacturer's USB driver if needed, and close other programs
using its serial port. Follow the language and name/callsign prompts. Radio
discovery typically takes about a minute. Press `h` for help and `q` to quit
from the top level.

## Included controls

- Read signal strength, frequency and mode with `w`.
- Select bands and modes, enter a frequency, and tune using comma/full stop.
- Round the VFO frequency to the nearest kilohertz with `z`.
- Adjust receive/transmit offsets where supported.
- Set tuning steps and select a VFO where supported.
- English, German and Polish labels, help and getting-started guides.

The compact interface was tested with a Focus Blue 40. Radio responses omit
the `yac:` prefix and command keys are not echoed. Numeric values remain
visible while editing. Your screen reader provides speech and braille.
Use North American Computer Braille for braille input and output, as described
in the guides.

## Beta testing and feedback

The Windows demo has been tested during development with the Icom IC-705,
Yaesu FTX-1 and Yaesu FTDX10. Other supplied radio definitions need further
hardware testing. This package is for 64-bit Windows; Linux and macOS require
the separate source setup.

This is a limited beta. Please report your Windows version, radio model and
steps to reproduce a problem. Contact Gena via the Active Elements or Blind
Hams email lists, or at gena@m0ebp.uk.

Diagnostic logging is enabled in this beta. The program creates
`logs/yac-debug.log` automatically. Sharing that log is optional: it can
include your name or callsign, device details and operating frequencies.
Review it before sharing. The download starts with blank personal settings
and contains no developer logs or saved radio connections.

A SHA-256 checksum is supplied as **YAC-001-beta-2026-10-10.sha256**.
