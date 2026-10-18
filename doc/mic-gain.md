Mic Gain adjustment
===================

Settings `s m` opens `modules/mic_gain.py`. It changes only microphone gain,
and only in response to full stop/comma. PTT, RF power, frequency, mode and
speech processing remain under the user's control. There is no automatic
transmission, low-power change, AM selection or automatic gain adjustment.

One short readiness prompt directs users to h for the preparation sequence.
Space proceeds; q cancels. The full procedure is in help, with model-specific
scales and exceptions in doc/supported-radios.

Start in receive. Hold physical PTT and speak normally, then release it.
During idle keyboard input, YAC reads TX status and samples ALC about every
0.3 seconds plus CAT response time. On return to receive it announces the peak.
Short peaks may be missed. Missing/partial responses are unknown, not zero.
These are raw CAT units, not watts or calibrated percentages, and no automatic
Good/Low/High verdict is made. Verify meter-zone calibration on physical radios
before introducing such judgements.

With PTT released, full stop increases mic gain and comma decreases it. Changes
are read back; successful changes announce gain and reset the captured peak.
`v` reads current gain; Space resets peak; `q` returns to Settings with Back.
The selected gain is retained. Release physical PTT yourself before leaving.
Mode changes end the session; connection loss ends adjustment. No other radio
settings require restoration because none were changed by the module.

Coverage
--------

FTDX10, FT-710, FTX-1: MG read/write (0-100), TX read, RM4 ALC read (0-255).
Icom IC-705, IC-7300, IC-7300MK2, IC-7600, IC-9700: CI-V 14 0B gain (BCD
0-255), 1C 00 RX/TX read, 15 13 ALC read. Native gain steps are 3, displayed
as rounded percentages. CAT gain steps are 1. Endpoints stop without wrapping.
TS-590SG and positively identified TS-480: MG gain (0-100), IF RX/TX status,
RM read. TS-590SG ALC uses 0-30 dots; TS-480 uses 0-10 dots. No RM3 meter
selection is sent; if ALC is not returned, the user selects that meter.
ID020 without verified TY identification (including QMX) remains unsupported.

SSB is supported. Yaesu/Icom AM can provide raw ALC, with Icom audio clarity
checked independently using monitoring or another station. Kenwood AM uses
power-meter response rather than this ALC procedure, and is not enabled here.
FM/data/CW/digital voice require separate mode-specific work and are not enabled.

Manufacturer references
-----------------------

- Local Yaesu FTDX10 CAT reference 2308-F and FTX-1 CAT reference 2508-C:
  `local_storage/manuals/pdfs`.
- [FT-710 CAT reference](https://www.yaesu.com/Files/4CB893D7-1018-01AF-FA97E9E9AD48B50C/FT-710_CAT_OM_ENG_2306-C.pdf).
- Local Icom IC-705 and IC-7300MK2 CI-V references: `local_storage/manuals/pdfs`.
- [IC-7600 manual](https://www.icomeurope.com/wp-content/uploads/2020/11/IC-7600_IM_D_upgrade_20151103.pdf).
- Local Kenwood TS-590SG command reference: `local_storage/manuals/pdfs`.
- [TS-480 command reference](https://www.kenwood.com/i/products/info/amateur/ts_480/pdf/ts_480_pc.pdf).
- [FTX-1 operating procedure, page 38](https://www.yaesu.com/Files/4CB893D7-1018-01AF-FA97E9E9AD48B50C/FTX-1_OM_ENG_EH084M201_2506E-DS.pdf).

Automated tests cover preparation cancellation, readback failure, native and
BCD gain changes, endpoints, identity gating, receive-state gating, mode changes,
sampled peak capture, raw meter parsing and return to Settings. Physical-radio
testing remains pending. AGC and speech-processor adjustment are separate work.
