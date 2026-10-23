Settings controls
=================

`s`, then `u`, opens Update YAC. Space confirms the handover after closing the
radio; `q` cancels. The updater offers release notes and a separate explicit
install choice. See [Updating YAC](updating-yac.md) for platform details.

`s`, then `w`, opens Wi-Fi setup on the configured Raspberry Pi image only.
Other installations use their operating system's Wi-Fi controls.

`p` cycles the supported preamp stages and off. `u` cycles the supported
attenuator levels and off. Radios with a single attenuator level toggle on/off;
FT-DX10 and IC-7600 also expose 6, 12 and 18 dB.

Top-level `v` reads the connected radio and reports attenuator, preamp,
configured power and tuner status in that order. Example in the demo:

    Attenuator off, preamp 2, power 20 watts, tuner off

`s`, then `t`, cycles tuner settings. Repeat `t` to advance; `q` leaves Settings.
Each `q` that returns from a submenu displays `Back`, including each level of
nested filter controls. At the top level, `q` exits with `Bye` and the user name.
Settings `v` continues to select a VFO. Changing tuner selection does not start
tuning. Top-level `t` starts the configured tuner; see `tuner-controls.md`.

Capabilities and live state
---------------------------

Each model has `settings.json` in its existing directory under `rad_cmds`.
The file contains supported features, protocol commands, reply formats,
valid states and language-label identifiers. Missing features are unsupported,
not off. In particular the IC-9700 has no tuner entry, so verification omits it
and Settings `t` reports Not supported without sending a tuner command.

`modules/verify_settings.py` loads the connected model's capability file and
uses the existing CAT/CI-V transport. `yac.py` only routes the keyboard commands.
The settings module does not keep a copy of current radio settings or change
band recall. Settings are read live; supported settings that fail to read are
reported as unknown. A setter must be acknowledged where the protocol supports
it and confirmed by readback before a successful change is reported.

All new labels are provided in English, German, Polish and Spanish. Feature
labels include explicit off, unknown, and unavailable responses.

Tuner distinctions
------------------

Tuner status describes the radio's configuration. An independent RF-sensing
external tuner cannot be detected. FT-DX10 exposes internal and external 1/2/3
selection; FTX-1 exposes internal, internal fast, external and ATAS. Model
variant, connected hardware, frequency and firmware may prevent a particular
selection; rejected or unconfirmed changes are reported as failed.

Turning a conventional tuner off retains its selected device. ATAS tuning stop
does not disable ATAS selection: switching ATAS off selects the disabled internal
tuner instead. Selection is checked before enabling the new tuner. Failed
multi-command changes can leave the tuner disabled; YAC reports the failure and
`v` reads its actual state. Settings `t` does not change an actively tuning state.

FT-991A and Icom CI-V tuner commands do not identify internal versus external
hardware, so their report uses tuner on/off. IC-705 has an external tuner state.
Kenwood reports the internal tuner's transmit bypass state.

Power and preamps
-----------------

`s`, then `p`, opens a whole-watt power edit. Blank Enter cancels; `h` followed
by Enter displays power help and returns to the field. Invalid entries leave
the field open. After a successful write and readback, YAC repeats the entered
value, for example `33W Set`. This confirms the requested setting, not an exact
measurement of transmitted watts. Blank cancellation and failed changes do not
show this confirmation. Leave Settings with `q` and use top-level `v` to report
the radio setting. Icom entries are converted to an estimated
relative setting using model/band ratings, rather than measured output.
IC-705 uses a 10-watt scale, with a 5-watt battery entry limit read from its
supply status. IC-9700 uses 100/75/10-watt scales by selected band. AM limits
and FTX-1 field/amplifier selection are checked before writing.

Yaesu and Kenwood report configured power in watts. The supported Icom command
reports a relative 0–255 setting: verification expresses that scale as a rounded
percentage, not an inferred watt value or a measurement of transmitted power.

FTX-1 preamp commands address HF/50 MHz, VHF or UHF according to the selected
frequency; VHF/UHF expose on/off. IC-9700 distinguishes internal and external
preamp activation, rather than calling its external preamp “preamp 2”.

Validation
----------

`a` adjusts AF Gain; `r` adjusts squelch in FM and RF Gain otherwise. Both
start at live values and display rounded percentages. Full stop increases,
comma decreases, and values stop at each end. The native step is 8 on a
0–255 scale, or 3 on the FT-DX10/FT-991A 0–100 squelch scale. Readback is
checked after changes, including selected-side commands on FTX-1.

Automated tests exercise the keyboard loop, demo behavior, real CI-V frame
encoding/decoding with echoed replies, rejected writes, CAT readback mismatch,
unknown states, no-tuner capabilities, FTX-1 band selection and ATAS handling.
No physical radio was changed or tested as part of this implementation.

Command references: the local Yaesu FT-DX10/FTX-1, Kenwood TS-590 and Icom
IC-705/IC-7300/IC-7300MK2 command manuals, plus the manufacturer's
[FT-991A CAT manual](https://www.yaesu.com/Files/4CB893D7-1018-01AF-FA97E9E9AD48B50C/FT-991A_CAT_OM_ENG_1711-D.pdf),
[IC-9700 CI-V guide](https://www.icomfrance.com/uploads/files/produit/not-IC-9700_ENG_CI-V_3a-en.pdf)
and [IC-7600 manual](https://www.icomeurope.com/wp-content/uploads/2020/11/IC-7600_IM_D_upgrade_20151103.pdf).

FTX-1 hardware-log correction
-----------------------------
The user's 40 m Optima trace (17 October) reports AC100, EX0301040 and
rejects AC001 with ?. This confirms the AC P1 error in Carl Obermeier's
hardware-tested FTX-1 CAT Manual Errors, item 2. EX030104 is OPTION/ATAS,
not the four tuner types (document-only errata item 13). Tuner type is selected
through EX030701 (ANT1) or EX030702 (ANT2), using EX030704/030703 to choose
the transmitting antenna. Separate RX routing still uses TX ANT1.

modules/ftx_tuner.py now owns FTX-1 selection/status/tuning. Settings t cycles
INT/INT FAST/EXT/ATAS on Optima; Field offers EXT/ATAS. It checks readback,
restores changed menus on failure and never sends AC enable/tune commands
while selecting. The general routing menu only receives 0 (OPTION) or 1 (ATAS).
A selected tuner type and an idle cycle are reported separately: AC100 does
not establish bypass Off, so a persistent Off choice is not fabricated.
Top-level t sends AC103 for both Optima internal and external paths, AC123
for ATAS; stop uses AC000 or AC120. Idle after observed activity reports
cycle finished, not successful matching. All previous FTX-1 AC001/AC003
assumptions and global four-choice menu definitions are superseded.

References:
https://github.com/captobie/ftx1-remote/blob/main/FTX-1%20CAT%20Manual%20Errors.md
https://github.com/captobie/ftx1-remote/blob/main/ftx1-cat-manual-errata.md
https://github.com/Hamlib/Hamlib/blob/master/rigs/yaesu/ftx1/ftx1_ext.c
https://github.com/Hamlib/Hamlib/blob/master/rigs/yaesu/ftx1/ftx1_tx.c

The trace proves the old rejection; corrected menu writes and tuning still
need a physical-radio retest. No live radio was accessed during this fix.
