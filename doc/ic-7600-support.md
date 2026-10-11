# Icom IC-7600

Sources: [Icom instruction manual](https://icomuk.co.uk/files/icom/PDF/productManual/IC-7600_ENG_3.pdf),
[updated manual with command tables](https://www.icomeurope.com/wp-content/uploads/2020/11/IC-7600_IM_D_upgrade_20151103.pdf),
and [Icom firmware 2.00 notes](https://www.icomjapan.com/support/firmware_driver/2387/).

YAC probes the factory address 7A and identifies the model through command
19 00, including at a changed address. Set the radio and interface to matching
CI-V baud rates; close other software using the serial port.

The profile supports 30 kHz–60 MHz reception, HF/6 m band navigation,
frequency entry/steps, signal reports, and the documented analogue modes
including PSK and PSK-R. S-meter interpolation is approximate.

In Settings, `v` selects Main first and Sub next, using 07 D0/D1.
The IC-7600 does not use the VFO A/B commands of the IC-7300.
RIT/Delta-TX controls and offset-preserving rounding require firmware 2.00's
21 commands. Older firmware may reject these controls; basic tuning and status
remain available. This package does not update radio firmware.

Acknowledgements and readback validate changes. Coverage is simulated;
Miguel's physical radio still needs testing. CTCSS and data submode selection
are outside this profile's current interface.
