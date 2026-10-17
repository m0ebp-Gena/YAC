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
