Tuner operation
===============

Select and enable the desired tuner with Settings, t. At the top level, t
starts one native tune cycle. It can transmit the radio's tuning signal.
Tuner off is reported without enabling a different device or starting RF.
No frequency, mode, power or tuner-selection menu is changed by YAC.

Profiles: FT-DX10 and FT-710 AC002; FTX-1 AC003 (internal/fast),
AC103 (external), AC123 (ATAS); TS-590SG and TS-480SAT AC111;
IC-705, IC-7300, IC-7300MK2 and IC-7600 CI-V 1C 01 02.
TS-480HX, IC-9700 and QMX report Not supported. TS-480 requires live TY
identification before enabling the SAT profile. Independent RF-sensing tuners
cannot be identified or controlled through these commands.

Busy status prevents another start (Yaesu commands can toggle tuning).
Readback polls every half second for up to 60 seconds. Observed busy followed
by enabled/idle reports Tuning cycle finished, not successful SWR matching.
An ignored or very fast cycle which never reports busy is unconfirmed.
Bypass after start reports failure/bypass. Lost readback or timeout requests
native tuning stop, then checks it. Conventional tuner stop may bypass the
tuner; ATAS stop is AC120. No automatic retry or restart is performed.

References: local manufacturer CAT manuals for FT-DX10, FTX-1 and TS-590SG;
Yaesu FT-710 CAT manual (2306-C), Kenwood TS-480 PC command guide AC table,
and Icom model CI-V tuner control tables (1C 01).

Automated tests use simulated transports. Physical tuning still requires
operator testing. The private key chart is left for the user to mark.

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
