# Icom IC-9700

The IC-9700 profile is based on the manufacturer's [CI-V Reference Guide,
revision 3a](https://www.icomfrance.com/uploads/files/produit/not-IC-9700_ENG_CI-V_3a-en.pdf)
and [official specifications](https://www.icomjapan.com/lineup/products/IC-9700/).
It has offline simulation coverage; physical IC-9700 testing is still needed.

Discovery recognises the factory address A2 and reads the transceiver ID with
19 00, including when the user changes its CI-V address. Existing USB/serial
discovery and saved connection profiles apply.

The profile provides frequency and mode reading/setting, S-meter reports,
frequency steps, band navigation across 2 m/70 cm/23 cm, VFO A/B selection,
receive RIT, FM CTCSS/DTCS tones and frequency rounding. Commands 03/04/05/06, 07 00/01,
15 02 and 21 00/01 are documented in the guide. A/B selects VFOs within the
current band; it does not select MAIN/SUB. In satellite mode, the radio may
reject VFO B selection; YAC keeps its previous selection unless acknowledged.

RIT is supported; XIT is not. YAC reports unsupported transmit offset without
sending 21 02. Clearing offsets clears RIT. Signal conversion uses the documented
0=S0, 120=S9, 241=S9+60 endpoints with approximate intermediate interpolation.

Frequency entry rejects gaps between the three bands. The profile allows the
widest documented USA ranges (144–148, 430–450, 1240–1300 MHz). European and
other regional radios impose their own narrower ranges; rejected settings are
reported and restored using YAC's normal acknowledgement/readback checks.

Modes are LSB, USB, AM, CW, RTTY, FM, CW-R, RTTY-R, DV and DD (22).
DD is offered only on 23 cm after command 16 5A confirms satellite mode OFF.
No WFM is offered. The radio's acknowledgement and mode readback still determine
whether any requested mode change succeeded.

Shared command files 25/26 address selected/unselected VFOs on MAIN only;
they are not a satellite or SUB-band control implementation. Satellite tracking,
D-STAR callsign configuration, memory programming and MAIN/SUB selection are
outside the current interface. This profile does not add transmission controls.

FM tone commands follow 1B 00/01/02 and 16 5D, with CTCSS/DTCS
readback verification. The interface offers TX or Both, including normal/inverted
DTCS polarity, on the three supported bands.
