# Antenna control — 17 October 2026

Top-level x opens Antennas and reads current TX/RX routing without changes.
Repeat x cycles supported main antennas. r controls the optional receive path.
h reads antenna help; q leaves with Back. Another command exits and is passed
to the top level. Settings has no antenna alias.

Labels and h012 help are provided in English, German, Polish and Spanish.
The private key chart is deliberately left unchanged: the user will add its
implementation asterisk. Physical-radio testing remains pending. No installer
build made.

## Model behaviour

- FT-DX10, FT-710, IC-705 and original IC-7300: fixed antenna 1 is reported;
  cycling and receive-path changes say Not supported.
- TS-590SG: x changes ANT1/2 preserving RX ANT and the Drive Out/antenna-output
  field. r changes RX ANT preserving the other fields; unchanged CAT fields
  are sent as 9 as specified by Kenwood.
- TS-480HX/SAT: x changes ANT1/2 after the existing TY identity check. r is
  unavailable. Shared ID020 alone does not enable this on QMX.
- IC-7600: x changes ANT1/2 while preserving RX path state; r changes the RX
  path while preserving the main antenna selection.
- IC-7300MK2: fixed main antenna, with r controlling RX-ANT IN/OUT. The RX
  path may contain a filter/preamp rather than a separate receiving antenna.
- FTX-1 with SPA-1: HF/50 MHz only. A PC response with selector 2 is required
  as the SPA-1 command-context guard; this needs physical confirmation on
  Field and Optima variants and is not a general hardware inventory query.
  In normal TRX mode x cycles ANT1/2. r requires TX ANT1 and enables ANT2
  reception using operation mode 2 and HF ANT SELECT 1. Turning it off selects
  ANT1 before returning to TRX mode, keeping TX on ANT1 throughout. Existing
  mode 1 routing is also reported and can be returned to ANT1. x is unavailable
  while receive-only routing is configured: it must not turn a receive-only
  antenna into a TX path. No tuner-selection menu is changed.
- IC-9700 and other unprofiled models: Not supported. Band-specific sockets
  are not cycled as antenna alternatives. FT-DX101 remains future radio support;
  this module does not add discovery or general control support for that model.

## Verification and failure behaviour

Each user action starts from a fresh radio read and validates native values.
Every write is read back; Icom additionally requires acknowledgement. Failed
changes announce failure and the actual current routing if it can be read.
Unknown routing prevents changes. FTX-1 receive-path setup uses multiple menu
writes: a partial failure may leave an intermediate routing, which is reported
rather than pretending success or automatically changing it again.

No transmitter is keyed. Antenna switching is separate from tuner selection.
Mappings are in per-model antennas.json; implementation is antenna_control.py.
Protocol and keyboard tests use offline radios, not physical hardware.

Manufacturer documentation and remaining FT-DX101 documentation discrepancies
are recorded in antenna-control-survey.md.
