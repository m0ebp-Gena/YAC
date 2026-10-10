# FTX-1 CAT documentation: hardware evidence from YAC

Prepared 6 October 2026. Draft for GitHub; this file has not been posted.

## Reproducible SM1 response prefix discrepancy

Reference: FTX-1 CAT Operation Reference Manual, revision 2508-C, printed
page 25, SM S-METER READING. The manual defines P1 as 0 for Main and 1 for
Sub, and shows the answer as SM followed by P1 and three meter digits.

On the tested FTX-1, a Sub meter read returned an SM0 prefix instead of SM1.
Three alternating query pairs reproduced this behaviour. Identification and
automatic information were read first:

```text
TX ID;    RX ID0840;
TX AI;    RX AI0;
TX FA;    RX FA007100000;
TX FB;    RX FB145500000;
TX MD0;   RX MD01;
TX MD1;   RX MD14;

TX SM0;   RX SM0124;
TX SM1;   RX SM0000;
TX SM0;   RX SM0124;
TX SM1;   RX SM0000;
TX SM0;   RX SM0124;
TX SM1;   RX SM0000;

TX RM0;   RX RM0124000;
TX RM1;   RX RM1124000;
TX RM2;   RX RM2000000;
```

Transport: direct USB Enhanced COM22, 38400 baud, 8N1, RTS/DTR deasserted.
Each query cleared the receive buffer, and the response was collected before
the next query. AI0 indicates automatic information was disabled. These were
read-only probes; no front-panel receiver swap was used.

The RM readings agree with Main raw 124 and Sub raw 0 at the sampled time.
This supports using RM0's separately identified fields as a workaround. It
does not prove SM1's physical receiver mapping under every operating condition.

Suggested report wording: please document the SM1 answer-prefix behaviour or
confirm a firmware correction. Firmware version was not recorded, so this
finding is specific to this tested radio; independent confirmation on other
firmware and in dual receive would strengthen it.

Raw evidence: ../logs/radio-targeted-check.json. The longer command regression
also observed the same prefix during multiple Sub operating modes:
../logs/radio-live-check.json.

## Comparison with the existing GitHub reports

Reviewed both public reports in captobie/ftx1-remote:

- [Hardware findings](https://github.com/captobie/ftx1-remote/blob/main/FTX-1%20CAT%20Manual%20Errors.md)
- [Document-only audit](https://github.com/captobie/ftx1-remote/blob/main/ftx1-cat-manual-errata.md)

Neither downloaded report lists this SM1 prefix discrepancy. Their C4FM notes
were considered while testing MD commands. YAC successfully set and read both
H and I on Main and Sub; the H/I parsing failure was in YAC's regular expression,
not a newly established manual error.

The existing reports disagree on HF maximum-power units; the hardware report
corrects the earlier document-only inference. We did not test that command,
so this report adds no claim about power units or other EX menu discrepancies.

## Findings excluded from the documentation correction

These were YAC bugs, corrected locally and covered by regression checks:

- MD parsing excluded the documented H/I codes.
- Status and mode-selection responses used inconsistent hyphenated mode names.
- IC-705 tone mode used 1A 05 instead of 16 5D.
- IC-705 DCS encoding placed the polarity byte after the code instead of before.
- Tone setting could claim success without a readback on Yaesu, or rely on a
  setter returning a response on Kenwood.
- Missing localized help/band messages and concatenated nested help responses.

These do not belong in an FTX manual correction issue.
