# YAC — Yet Another Controller

YAC is a keyboard-operated amateur radio controller designed with speech and
braille access in mind. It runs in a terminal and uses your screen reader for
speech and braille output. The current version is **001 beta**.

Controls include reading signal strength, frequency and mode; tuning; band and
mode selection; and receive/transmit offsets where supported. English, German
and Polish labels and help are included. Press `h` for help and `q` to quit
from the top level.

The Windows demo has been tested during development with the Icom IC-705,
Yaesu FTX-1 and Yaesu FTDX10. Other radio definitions are present in the source;
their presence does not establish hardware compatibility. Linux and macOS
radio discovery, keyboard input and screen reader access need practical testing.

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
callsign prompts. Automatic radio discovery can take about a minute.

For the controls and braille settings, read [the English demo guide](demo-start-here.txt).
[German](demo-start-here-de.txt) and [Polish](demo-start-here-pl.txt) guides are
also available. The executable instructions in those guides apply to the
packaged Windows demo; the commands above apply to this source repository.

## Linux and macOS

From the downloaded or cloned repository, run:

```sh
sh install-yac.sh
```

The installer asks before creating `~/yac`, creates a private Python
environment and installs pyserial. See [Linux and macOS setup](doc/linux-macos-setup.txt)
for requirements, launch commands and radio access details.

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
.\.venv\Scripts\python.exe -m unittest test_install_yac test_radio_responses test_icom_7300 test_tone_input
```

The `radio_*_check.py` scripts are hardware checks; inspect them before use.
`build_demo.py`, `package_demo.py` and `package_source.py` prepare distribution
packages. See [platform and packaging notes](doc/platform_setup_and_packaging.txt)
and [planned work](TODO.md).

## Feedback

Contact Gena through the Active Elements or Blind Hams email lists, or at
gena@m0ebp.uk. Include the YAC version, operating system, radio model and steps
to reproduce any problem.
