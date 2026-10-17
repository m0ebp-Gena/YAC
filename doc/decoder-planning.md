Decoder submenu planning
========================

Bindings (implementation status below):
c CW operating controls; c k Keyer speed.
d Decoders; d c Decode CW; d r Decode RTTY; d h Help; d q Back.
Returning from a decoder should preserve capture; stopping is explicit.
Capture and terminal text review are now implemented; see decoder-controls.md.
CW operating controls and keyer-speed shortcuts remain planned.
Labels l271-l275 provide CW, Decoders, Decode CW, Decode RTTY and Keyer speed
in English, German, Spanish and Polish. These are reserved UI resources;
their presence alone does not mean the corresponding command is functional.

Confirmed hardware routes
-------------------------
TS-590SG: CD0 decoder enable; CD1 threshold 001-030; unsolicited CD2 decoded
ASCII when AI is enabled (AI2 nonpersistent enable). Speed tracks automatically.
Read and preserve existing AI and decoder settings. Existing CAT transport
clears pending input, so a shared buffered reader is required before capture.
The command guide has apparent CD0 answer and missing read-terminator typos;
verify responses on hardware rather than reproducing those assumptions.
https://www.kenwood.com/i/products/info/amateur/pdf/ts590_g_pc_command_e_rev2.pdf
https://www.kenwood.com/i/products/info/amateur/pdf/TS-590SG_IDM.pdf

IC-705: built-in RTTY decoder exports decoded data on USB Serial Port B.
Port A remains CI-V. USB (B) Function = RTTY Decode, not RTTY keying.
CI-V 1A 05 01 33 reads/sets USB (B) Function: 00 Off, 01 RTTY Decode,
02 DV Data, 03 Weather. Preserve prior function and avoid interfering with
existing port-B applications or DTR/RTS SEND/keying assignments. Opening this
port needs deliberate line-state handling. Baud rate and exact stream framing,
decoder operation and identification of the matching physical device's port B
still require checking before implementation. No built-in CW text route found.
https://www.icomeurope.com/wp-content/uploads/2024/06/IC-705_ENG_IM_Basic_7.pdf
https://www.icomeurope.com/wp-content/uploads/2020/08/IC-705_ENG_CI-V_1_20200721.pdf

No documented CW decoded-text output found in the checked FT-DX10, FTX-1 or
IC-7300MK2 CAT/CI-V references. Decoder settings or screen text alone do not
establish an export route. Computer audio decoding would be a separate option.
