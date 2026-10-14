# Kenwood TS-480 support

Implemented from Kenwood's
[PC command reference](https://www.kenwood.com/i/products/info/amateur/ts_480/pdf/ts_480_pc.pdf)
and [instruction manual](https://manual.kenwood.com/en_contents/attachDownload/97416/).
This is implemented support with automated protocol tests. Physical TS-480
testing has not yet been performed; discovery alone was previously insufficient
to justify describing the radio as supported.

The TS-480 and QMX/QMX Plus share ID020. YAC reads TY to distinguish the genuine
Kenwood and its HX, SAT, Japanese 50 W or Japanese 20 W variant before enabling
TS-480-specific gain, power, tuner, tone and offset controls. The TY response is
read-only. These controls remain unavailable when identification is inconclusive.
The QMX's existing filter handling uses its own MM menu commands.

Implemented TS-480 operations:

- Signal dots, current receive VFO frequency and mode (`w`). Frequency entry,
  punctuation tuning and rounding use FA or FB according to FR; the inactive
  VFO is preserved. Frequency setting checks readback and restores after failure.
- Band navigation uses native BU/BD without the TS-590SG's band-number parameter.
  Mode selection supports LSB, USB, CW, FM, AM, FSK and reverse CW/FSK.
- AF Gain and squelch use 0–255; RF Gain uses the TS-480's 0–100 scale, rather
  than the TS-590SG's 0–255 scale. Readback confirms changes.
- Preamp and attenuator on/off, plus settings verification.
- Power editing uses variant-specific maxima: HX 200 W, SAT 100 W, Japanese
  types 50/20 W. HX is limited to 100 W on 50 MHz. AM maximum is one quarter
  of the applicable band maximum. Minimum is 5 W.
  This is configured power, not measured RF output.

  Band and AM limits follow Kenwood's
  [TS-480 specifications](https://www.kenwood.com/i/products/info/amateur/ts_480/).
- SAT tuner selection/bypass. HX and unidentified tuners are omitted. These
  commands never initiate tuning; independent/external tuners are not detected.
- FM CTCSS transmit tone or transmit/receive CTCSS, with Kenwood's verified
  42-frequency table. DCS and 1750 Hz burst are not implemented.
- `s v` switches the receive VFO A/B using FR and preserves FT/transmit VFO.
  This may leave the radio operating split; it deliberately preserves the
  transmit selection rather than silently changing it.
- Receive/transmit offset uses IF readback, RU/RD in 10 Hz steps, RT/XT and RC.
  The offset register is shared by RIT and XIT, as in the radio. Active scanning
  blocks offset adjustment because RU/RD have scan-speed meanings during scans.
- Direct bandwidth and separate Low/Upper Cut controls as described in
  [filter controls](filter-controls.md).
- Noise Blanker on/off and level 1–10 via NB/NL, using `f b`, repeated `b`
  and full stop/comma. FM mode is unsupported; level stays unchanged while Off.
- Noise Reduction via `f r` and repeated `r`. NR1 offers Auto and levels 1–9;
  NR2 adjusts following time from 2 to 20 milliseconds. The last observed type
  is retained when toggling on; NR1 is used when none is known and in FM mode.
- `f a` toggles Beat Cancel in SSB/FM/AM; repeated `a` toggles again. BC1/BC2
  is retained from the last observed selection, defaulting to BC1 when unknown.
  YAC announces Beat Cancel rather than Auto Notch. Manual Notch is unsupported.

Memory operations and transmit/tune initiation remain outside YAC's implemented
controls. Frequency operations require VFO mode; FR2 memory mode is not handled.
Regional hardware limits remain enforced by the radio and checked by readback.
