# Antenna switching survey — 17 October 2026

Research for the agreed top-level x control. The first implementation is now
documented in antenna-controls.md. No physical testing performed; the user
will mark the private key chart.

## Manufacturer findings

| Model | Main antenna choice | Separate receive routing / command notes |
| --- | --- | --- |
| FT-DX10 | One antenna connector; no normal antenna-switch control found in the CAT command list. | Do not invent an ANT 1/2 cycle. |
| FT-710 | No AN command found in the surveyed CAT reference. | Do not infer switching capability from commands supported by another Yaesu. |
| FTX-1 with SPA-1 / Optima | Two HF/50 MHz antennas; `EX030704;` reads HF ANT SELECT, 0=ANT1, 1=ANT2. | `EX030703;` reads ANT2 OPERATION: 0=TRX, 1=TX-ANT1/RX-ANT2, 2=TRX-ANT1/RX-ANT2. RX routing must be reported with the selected antenna. This is not the tuner-selection menu. SPA-1 presence and applicable band must be established before offering changes; Field-only and VHF/UHF sockets are not interchangeable alternatives. |
| FT-DX101MP/D | AN command addresses MAIN/SUB separately: `AN0;`/`AN1;`, with antenna values 1/2/3. | Set is `AN` + receiver + antenna; reply additionally has a fixed trailing 0. ANT3 SELECT configuration changes whether ANT3 is usable for TX or receive-only. The CAT menu table lists fewer ANT3 settings than the operational addendum; reconcile firmware and documentation before implementing receive-routing changes. This model is surveyed for future support, not claimed as already supported by YAC. |
| TS-590S/SG | `AN;` reads three fields; first 0=ANT1, 1=ANT2. | Second field enables RX ANT; third is Drive Out, or SG antenna-output status depending on its menu configuration. Set unchanged fields to 9: main antenna change can use `AN099;`/`AN199;`, RX change `AN909;`/`AN919;`. Do not alter the output field. |
| TS-480HX/SAT | `AN;`, `AN1;`, `AN2;`. | One antenna field using 1/2, unlike TS-590's 0/1 plus two additional fields. No RX ANT selector is documented in the checked command entry. Verify TS-480 identity; QMX shares CAT ID020 and must not inherit this capability. |
| IC-7600 | CI-V 12 selects ANT1/ANT2 together with RX ANT state. | Two bytes: `00 00` ANT1/RX off; `00 01` ANT1/RX on; `01 00` ANT2/RX off; `01 01` ANT2/RX on. Preserve the other field for each user action. RX ANT IN/OUT can also be an external filter/preamp loop; do not always call it a separate physical receive antenna. |
| IC-7300MK2 | Single main antenna, plus RX-ANT IN/OUT facilities. | Supplied CI-V guide documents command 12, antenna selector 00, receive-path data 00/01. Offer the receive-path control rather than an invented main-antenna cycle. Do not transfer this capability to the original IC-7300. |
| IC-705 / original IC-7300 | No main-antenna switching established by this survey. | Do not send IC-7600/7300MK2 switching commands merely because these radios use CI-V. |
| IC-9700 | Band-specific antenna sockets. | Socket count is not an ANT1/ANT2 choice for a given band; do not offer them as switchable alternatives. |

## Consequences for the proposed controls

- First x reports routing without changes. Repeat x cycles only main choices
  actually supported in the current radio/hardware/band configuration.
- r controls an optional receive path where documented; single-main-antenna
  radios can still have a useful r action. Unsupported actions say so.
- On FTX-1 and FT-DX101, receive routing is more than a generic Boolean. Do not
  change a configured RX-only port into a transmitting port as a side effect
  of cycling the main antenna. Agree how the FTX-1's two receive modes should
  map to r before implementing that part.
- Read current routing and confirm each change. Preserve tuner selection,
  Kenwood Drive Out/antenna output, other receiver settings, and unrelated
  configuration. Report TX and RX separately, using unknown for failed reads.
- q leaves with Back; h gives help. No antenna-switching code or tests have
  been added as part of this research.

## Primary references checked

- [FT-DX10 CAT reference](https://www.yaesu.com/Files/4CB893D7-1018-01AF-FA97E9E9AD48B50C/FTDX10_CAT_OM_ENG_2308-F.pdf) and manufacturer operating-manual connection diagram.
- [FT-710 CAT reference](https://www.yaesu.com/Files/4CB893D7-1018-01AF-FA97E9E9AD48B50C/FT-710_CAT_OM_ENG_2306-C.pdf).
- FTX-1 supplied CAT 2508-C: `local_storage/manuals/pdfs/FTX-1_CAT_OM_ENG_2508-C.pdf`, EX menu 03/07/03-04.
- [FTX-1 advanced manual](https://www.yaesu.com/Files/4CB893D7-1018-01AF-FA97E9E9AD48B50C/FTX-1_AM_ENG_2506-B.pdf), printed page 76; [SPA-1 manufacturer leaflet](https://www.yaesu.com/Files/4CB83B95-1018-01AF-FAD307DB330C321A/FTX-1_Series_leaflet_ENG_2505.pdf).
- [FT-DX101 CAT 2308-L](https://www.yaesu.com/Files/4CB893D7-1018-01AF-FA97E9E9AD48B50C/FTDX101MP_D_CAT_OM_ENG_2308-L.pdf), AN and EX ANT3 SELECT; [operational addendum](https://www.yaesu.com/Files/BB2B47AE-1018-01AF-FAE48FDCB1919193/Important%20Changes.pdf).
- TS-590S/SG supplied PC command reference: `local_storage/manuals/pdfs/ts_590_g_pc_command_e.pdf`, AN entry.
- [TS-480 manufacturer PC command reference](https://www.kenwood.com/i/products/info/amateur/ts_480/pdf/ts_480_pc.pdf), AN entry.
- [IC-7600 manufacturer manual](https://www.icomeurope.com/wp-content/uploads/2020/11/IC-7600_IM_D_upgrade_20151103.pdf), CI-V table printed page 159, RX ANT connections and antenna selection sections.
- IC-7300MK2 supplied CI-V reference: `local_storage/manuals/pdfs/IC-7300MK2_ENG_CI-V_0.pdf`, command 12; [manufacturer RX-ANT description](https://www.icomjapan.com/lineup/products/IC-7300MK2/).
- [IC-9700 manufacturer specifications](https://www.icomjapan.com/lineup/products/IC-9700/), band-specific antenna connectors.
