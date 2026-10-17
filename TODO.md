# YAC TODO

- [ ] **Urgency: medium.** Create an optional BRLTTY setup script to enable the North American computer braille table (`text-table en-nabcc`) in `/etc/brltty.conf`, saving users from editing the file themselves. Back up the existing configuration, uncomment or add the directive, and handle any conflicting active text-table setting so only the chosen table is active. Preserve unrelated settings and make repeated runs safe. Establish whether the user wants a braille display before offering this setup. Strongly recommend a direct wired USB connection for initial setup; leave Bluetooth for later, once wired access works. Preserve BRLTTY's automatic display detection rather than requiring driver/device changes when it already works. Gena reports both of her displays worked over direct USB with the default configuration; uncommenting the North American computer braille table line was the only change needed.

- [ ] **For 13 October 2026:** Create a public supported-radio list in two parts: radios tested with physical hardware, and radios with implemented support that have not yet been tested with physical hardware. Check developer and tester reports before assigning either category; automated simulations do not count as physical-radio testing. State any important limits in the tested coverage and publish the list on GitHub.

- [ ] Audit help with feedback from new users: check discoverability, starting values, units, navigation, leaving submenus and help inside edit fields. Keep explanations short, accessible to speech and braille, and consistent across all four languages. Deferred for a future review.

- [ ] Consider less-than and greater-than keys (the ar and gh signs in computer braille) for jumping to the bottom or top of a scale, such as returning RF Gain quickly from 50 percent to maximum. Pending the user's decision; direction mapping and supported controls are not yet agreed. Do not implement yet.

- [ ] **Priority:** Reuse the currently unused label numbers `l055`, `l065`, `l082` and `l083` when implementing more controls. Add each reused label in English, German and Polish, and update the code references. These numbers are currently absent from all three language folders and are not called by the code.

- [x] Extend `w` (Where am I?) to include the active CTCSS tone or DCS code when set, alongside signal strength, frequency and mode. Include DCS normal/inverted polarity and TX/Both where applicable. Read the radio's current setting so the report also reflects changes made using the radio's own controls.
