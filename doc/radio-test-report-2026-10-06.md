# YAC radio command regression — 6 October 2026

## Hardware coverage

IC-705: COM5, 115200 baud, CI-V address A4.
FTX-1: COM22, 38400 baud, CAT ID 0840; Main and Sub tested separately.
FTDX10: saved USB identity absent; no live tests possible in this session.
Kenwood TS-590: no configured/connected hardware; offline response checks only.

Live checks covered w/f status, frequency entry including invalid values,
all listed operating modes, frequency up/down, nearest-kilohertz rounding,
band up/down, offset zero/receive/transmit/clear, CTCSS TX/Both, and DCS where
supported. Every listed FTX mode, including H/I, accepted its mode command
and read back correctly on both receivers. IC-705 listed modes also passed.

The first run found IC-705 DCS failures and unknown Sub S-meter status. Focused
retests passed after corrections; raw first-run failures are retained in the
logs rather than overwritten. S-meter validation verifies response parsing and
the selected receiver; it does not independently calibrate RF signal strength.

## Corrections

- Consistent compact mode names in status and mode selection.
- Read FTX C4FM H/I codes correctly.
- FTX Sub meter: fall back to RM0's separate receiver fields when SM1's answer
  has the wrong prefix. Final Sub status: S 0 145.5 FM.
- IC-705 tone mode: documented 16 5D command; DCS polarity-byte ordering fixed.
- Verify tone frequency/code and mode readbacks before reporting success.
- Verify Yaesu offset really reached zero.
- Supply missing German/Polish help and band labels.
- Echo nested help requests so responses start on a new transcript line.
- English help now lists implemented controls and no longer advertises AF gain,
  which currently returns the unavailable-command response.

## Restored controls

Verified after live testing:

- IC-705: 14.185 MHz LSB, original mode/filter bytes, offset +40 Hz,
  RIT and XIT both enabled; original tone frequencies, DCS and tone mode restored.
- FTX Main: 7.1 MHz LSB, offset 0, RX/TX clarifiers disabled; original tones restored.
- FTX Sub: 145.5 MHz FM, offset 0, RX/TX clarifiers disabled; original tones restored.

No transmit/PTT or antenna-tune commands were tested. The implemented command
set does not include those actions. Tests temporarily changed VFOs and modes;
all mode-specific filter memories and all hardware band-stack slots were not
snapshotted, so restoration claims apply to the captured controls above.

## Offline coverage

12 passing regression tests in test_radio_responses.py, with parameterized
checks across FTDX10, FTX-1, TS-590 and IC-705 response formats. These cover
mode/status consistency, malformed frequency input without writes, rejected
frequency restoration including FTX Sub, missing-read cancellation, four step
families, tone rejection/readbacks, offset zero verification, localization,
Sub-meter fallback, and response cursor positioning.

The actual keyboard loop was exercised with simulated key/input and hardware
operations for each radio profile: nested help/q, forwarding another command
out of mode selection, settings persistence, FTX VFO selection, tone and offset
menus, stepping, rounding, unavailable commands, and clean serial close.
Physical braille-display and screen-reader behaviour needs user verification.

## Reproduction and evidence

Run offline tests with any Python runtime:

```text
python -m unittest tests.test_radio_responses
```

Live helpers require pyserial. The test dependency was installed in .test-deps;
set PYTHONPATH to that directory for the bundled Python runtime. Live helpers
change radio settings and should be run only when those changes are intended:
tests/hardware/radio_live_check.py and tests/hardware/radio_targeted_check.py. tests/hardware/radio_read_check.py only queries
the saved USB identities and leaves yac.ini unchanged.

Evidence: logs/radio-live-check.json, logs/radio-targeted-check.json, and
logs/radio-read-check.json. FTX documentation draft:
doc/ftx1-github-correction-report-2026-10-06.md.
