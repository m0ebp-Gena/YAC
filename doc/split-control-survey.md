# Split control survey — 17 October 2026

Original research for top-level `l`. The subsequent first implementation is
documented in `split-controls.md`; its chart entry is marked implemented.
No installer build or physical-radio testing performed.

## The distinction that matters

Split means receiving on one frequency and transmitting on another. The
operation must identify both roles, rather than treating "other VFO" as a
universal name for the transmitter. VFO selection, transmit selection, and
split enable are distinct model-dependent operations.

FM repeater duplex is also distinct from two-VFO split. CTCSS/DCS does not
itself configure either the transmit frequency or repeater shift.

## Verified command differences

| Radio | Split control | Frequency/VFO implications |
| --- | --- | --- |
| FT-DX10 | `ST;` reads; `ST0;` off, `ST1;` on. `ST2;` enables split with +5 kHz, so it also changes the operating setup. | `FA`/`FB` address named VFO A/B. `VS` selects A/B. `FT` **sets with 2/3 but answers with 0/1** for Main/Sub TX. Setter and response encodings cannot be shared. |
| FT-710 | `ST;`, `ST0;`, `ST1;`. The surveyed reference does not list the FT-DX10's `ST2` shortcut. | `FA`/`FB`, `VS`, and TX selection must be handled separately. `FT` uses 0/1 for both set and response. |
| FTX-1 | `ST;`, `ST0;`, `ST1;`. | `FA`/`FB` address Main/Sub. `FT0/1` chooses the transmitting side. **`FR00/01` controls dual/single reception**, not A/B receive selection. `VS` has Main/Sub TX/RX role semantics. Do not copy Kenwood `FR` logic. |
| IC-705 | CI-V `0F` reads split/duplex; `0F 00/01` sets split off/on. Responses also include `11/12` for DUP-/DUP+. | `07 00/01` selects A/B. `25 00/01` reads/sets selected/unselected frequency; `26 00/01` does the same for mode/data/filter. **00 and 01 are relative to the selected VFO, not fixed A/B identities.** DR and memory/call contexts have documented restrictions. |
| IC-7300MK2 | The supplied CI-V reference documents selected/unselected frequency and mode via 25/26. | Same relative selector distinction; retain per-model validation rather than inferring everything from the IC-705. |
| IC-9700 | `0F` also returns duplex states, including DD repeater simplex in the surveyed guide. | `25/26` selected/unselected access is **MAIN-band only**; it does not mean Main/Sub. Satellite mode rejects these operations. A/B split, Main/Sub selection, and satellite operation need separate handling. |
| TS-590SG | `FR` selects RX and `FT` TX, with 0=A, 1=B, 2=memory where allowed. | The reference explicitly says setting `FR` selects simplex, while setting `FT` selects split. A VFO-selection command can therefore change split state. |

IC-7300, IC-7600 and TS-480 require their own command/operating-guide checks
before inclusion in an implementation. Existing command-file entries are
implementation assets, not sufficient evidence of every operating restriction.
QMX must not inherit TS-480 split support merely because it shares CAT ID020.

## Findings in current YAC

- Icom profiles already provide read/set files for split, selected/unselected
  frequency and mode. These were present before the new top-level split control.
- Icom `s v` initially selects A, then alternates using remembered selections
  after acknowledgements. This is not a live query of which VFO was selected
  externally and must not become authoritative for split frequency reporting.
- FTX-1 `s v` changes YAC's local Main/Sub control target. It does not issue a
  radio `VS` command. YAC's control target must not be mistaken for TX routing.
- TS-480 VFO-selection code comments claim preservation of split; the TS-480
  reference needs checking before relying on that assertion. The TS-590SG
  reference demonstrates why `FR` semantics cannot be assumed harmless.

## Proposed behaviour to discuss before implementation

### Ian's FT Talk guide

Reviewed `local_storage/FTTALK_UserGuideV35.xhtml`, Split Frequency mode,
Repeater mode, CTCSS/DCS and Extended Command Mode sections.

- Outside FM, V enters split: receive on A, transmit on B, and navigation
  adjusts B's transmit frequency. V again exits split.
- In FM on the supported repeater bands, V instead enables repeater operation
  using a configured offset or a temporary offset from Extended O.
- Ordinary channel tuning keeps repeater operation active; changing mode,
  band or using the 1 MHz jumps turns it off.
- Repeater setup order is receive frequency, repeater operation, then tone/code.
- Normal frequency reporting gives the transmit frequency; Extended F gives
  receive frequency during split or repeater input frequency in repeater mode.
- Swapping Main/Sub or A/B is a separate operation, with a reminder to swap
  back after listening to the repeater input.

The split section does not specify whether entering split copies A into B;
do not infer an equalization command from that description. These are FT Talk
behaviours to discuss for YAC, not approval to change YAC's navigation or w.
Use a small dedicated module for the agreed control and per-model command
handling, leaving top-level dispatch in yac.py.

1. Establish whether `l` should simply toggle the existing split setup or
   open a control for entering a transmit frequency / signed offset. Do not
   silently choose a +5 kHz shortcut or overwrite the other VFO.
2. Announce the live split state and both roles, for example:
   `Split On, receive 14.195 USB, transmit 14.200 USB`.
3. Preserve the user's receive frequency, existing other-VFO contents, mode,
   data/filter selections, tone settings, and receiver arrangement unless the
   chosen action explicitly changes them. Changing mode with Icom 26 requires
   care: omitted data/filter fields can reset them to defaults.
4. Read back changes; handle unreadable state as unknown, not Off. Distinguish
   split, repeater DUP-/DUP+, and unsupported satellite/DR/memory contexts.
5. Keep the initial implementation in VFO mode where documented, and verify
   the model's TX-frequency mapping rather than inferring it from a cached
   selected-VFO variable. Do not key the transmitter for verification.

These are proposals, not an agreed key flow. Repeater-shift support can be a
separate action if the user wants it; it should not silently replace split.

## Manufacturer references

- [FT-DX10 CAT reference, 2308-F](https://www.yaesu.com/Files/4CB893D7-1018-01AF-FA97E9E9AD48B50C/FTDX10_CAT_OM_ENG_2308-F.pdf): FT, ST, VS, FA/FB.
- [FT-710 CAT reference, 2306-C](https://www.yaesu.com/Files/4CB893D7-1018-01AF-FA97E9E9AD48B50C/FT-710_CAT_OM_ENG_2306-C.pdf): FT, ST, VS.
- FTX-1 CAT reference **2508-C**, supplied locally at `local_storage/manuals/pdfs/FTX-1_CAT_OM_ENG_2508-C.pdf`; checked extracted FR, FT, ST and VS entries. The online [2507-B reference](https://www.yaesu.com/Files/4CB1CAF6-1018-01AF-FABABCA11697FC7F/FTX-1_CAT_OM_ENG_2507-B.pdf) is older; do not substitute it for the supplied revision.
- [IC-705 CI-V reference](https://www.icomeurope.com/wp-content/uploads/2020/08/IC-705_ENG_CI-V_1_20200721.pdf): command table and selected/unselected VFO sections.
- [IC-9700 CI-V reference](https://www.icomfrance.com/uploads/files/produit/not-IC-9700_ENG_CI-V_3a-en.pdf): 0F and MAIN-only 25/26 restrictions.
- IC-7300MK2 supplied CI-V reference: `local_storage/manuals/pdfs/IC-7300MK2_ENG_CI-V_0.pdf`, selected/unselected VFO sections.
- TS-590SG supplied PC command reference: `local_storage/manuals/pdfs/ts_590_g_pc_command_e.pdf`, FR/FT section.
