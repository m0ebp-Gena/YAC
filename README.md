# YAC — Yet Another Controller

YAC is a keyboard-operated amateur radio controller designed with speech and
braille access in mind. It runs in a terminal and uses your screen reader for
speech and braille output. The current version is **001 beta**.

Controls include reading signal strength, frequency and mode; tuning; band and
mode selection; AF Gain, RF Gain/squelch; preamp and attenuator selection;
editable output power; guided mic gain with sampled peak ALC; model-specific AGC preset selection; supported tuner settings; receive/transmit offsets;
receive bandwidth with separate low/upper cut controls, and Noise Blanker
and Noise Reduction toggle/adjustment controls; Auto/Manual Notch with width
selection, and TS-480 Beat Cancel where supported. New controls include split/repeater setup,
repeated Where Am I details, antenna routing and tune activation. The Decoders
submenu provides TS-590SG native CW, IC-705 native RTTY and experimental audio
CW with guided receive-input selection. See [decoder setup and limits](doc/decoder-controls.md).
English, German, Spanish
and Polish labels and help are included. Press `h` for help and `q` to quit
from the top level.

The Windows demo has been tested during development with the Icom IC-705,
Yaesu FTX-1 and Yaesu FTDX10. Other radio definitions are present in the source;
their presence does not establish hardware compatibility. Linux and macOS
radio discovery, keyboard input and screen reader access need practical testing.

Kenwood TS-480 support is now implemented from the manufacturer's command
reference, with automated checks; physical-radio validation is pending.
See [TS-480 coverage and QMX ID handling](doc/ts-480-support.md).

## Run from source on Windows

Install Python 3.10 or newer with the Python launcher. Download and extract
this repository, or clone it, then open PowerShell in its root folder:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe yac.py
```

After setup, `run-yac.cmd` also starts YAC using the local environment.
Keep `modules`, `lang` and `rad_cmds` alongside `yac.py`.

Connect your radio and close any other program using its serial port. Install
the manufacturer's USB driver if required. Follow the language and name or
callsign prompts. Automatic radio discovery can take about a minute. If no radio responds, YAC
loads an in-memory FT-DX10 demo so you can explore the controls. Signal strength
and radio settings are simulated; no demo connection is saved in yac.ini.

Keep [the English key binding chart](KEY-BINDINGS-English.txt) open in a separate
window while using YAC. It lists implemented commands and submenu sequences.
[German](TASTENBELEGUNG-Deutsch.txt), [Polish](SKROTY-KLAWISZOWE-Polski.txt) and
[Spanish](TECLAS-Espanol.txt) charts are also available. Update these public
charts whenever a command is implemented.

For startup, braille settings and troubleshooting, read [the English first-steps guide](demo-start-here.txt).
[German](demo-start-here-de.txt) and [Polish](demo-start-here-pl.txt) guides are
also available, along with [Spanish](demo-start-here-es.txt). The executable instructions in those guides apply to the
packaged Windows demo; the commands above apply to this source repository.

## Linux and macOS

From the downloaded or cloned repository, run:

```sh
sh install-yac.sh
```

The installer asks before creating or updating `~/yac`, preserves existing
settings and logs, and reuses its private Python environment and compatible
pyserial. Only new or changed program/data files are copied. See [Linux and macOS setup](doc/linux-macos-setup.txt)
for requirements, launch commands and radio access details.

For braille and console speech, see [BRLTTY display commands](BRAILLE-FS-START-HERE.txt)
and the [Pi BRLTTY speech guide](doc/pi-brltty-speech.txt). Initial Linux testing
has confirmed usable Freedom Scientific braille and the simulated-radio startup
line; broader hardware and sleep/wake testing remains ongoing.

Real connections are checked quietly every five seconds while waiting for
command keys. After repeated failures, YAC attempts to reconnect to the same
device and model without restoring radio settings or entering simulated mode.
The connection and simulated-mode messages stay under the terminal cursor
until a command is entered. Polling pauses during editable fields.

New Icom definitions are documented in [IC-7600 support](doc/ic-7600-support.md)
and [IC-9700 support](doc/ic-9700-support.md); those profiles still require
physical-radio validation.

## Settings and diagnostics

YAC creates `yac.ini` beside the program to save your preferences and discovered
radio connections. You may optionally copy `yac.ini.example` to `yac.ini`
before starting. Personal settings, logs, local reference material, Python
environments and generated builds are excluded from Git.

Diagnostic logging is available with `--debug`. Logs can contain names,
callsigns, device identifiers and operating frequencies; review them before
sharing. See [debugging instructions](doc/debugging.txt).

## Development

Offline regression tests can be run without a connected radio:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -t .
```

Tests live in `tests/`. Manual radio and braille checks live in `tests/hardware/`;
inspect them before use and run them as modules, for example
`python -m tests.hardware.radio_read_check`.
`build_demo.py`, `package_demo.py` and `package_source.py` prepare distribution
packages. See [platform and packaging notes](doc/platform_setup_and_packaging.txt)
and [planned work](TODO.md).

Find current release ZIPs and checksums in the project root. Older releases
are preserved in `previous-builds/<date>/`, with numbered subfolders for repeat
builds on the same date. Successful packaging archives the current release
before replacing it. Source and Windows packages from the same date can share
the root until a filename would be replaced. Runnable Windows files are kept
in `builds/runnable/`; temporary build files are in `builds/.work/`.
Generated packages and previous builds remain excluded from Git.

## Feedback

Contact Gena through the Active Elements or Blind Hams email lists, or at
gena@m0ebp.uk. Include the YAC version, operating system, radio model and steps
to reproduce any problem.

IC-9700 control support is based on Icom documentation and offline simulations;
hardware validation is still required. See [IC-9700 support notes](doc/ic-9700-support.md).

[IC-7600 support notes](doc/ic-7600-support.md) describe Main/Sub controls and
the firmware 2.00 requirement for RIT/Delta-TX. Hardware testing is pending.
