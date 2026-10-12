"""Portable Windows entry point; keep writable data beside YAC.exe."""
import sys
from pathlib import Path

import yac


def main():
    root = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    yac.project_root = lambda: root
    if "--check-package" in sys.argv:
        import serial
        from serial.tools import list_ports
        assert (root / "yac.ini").is_file(), "Missing yac.ini"
        for language in yac.lang_sel.LANGUAGE_CODES:
            assert (root / "lang" / language / "labels" / "l000").is_file(), language
            for token in ("l070", "l120", "l140", "l141", "l142", "l143", "l144", "l146"):
                assert yac._read_label(root, language, token, ""), (language, token)
            for help_tag in ("h005", "h006"):
                assert (root / "lang" / language / "help" / help_tag).is_file(), (language, help_tag)
        assert any((root / "rad_cmds").rglob("*")), "Missing radio commands"
        from modules.dummy_radio import create_dummy_radio
        radio = create_dummy_radio()
        assert yac.gain_control.adjust(yac, root, radio, "en", "a", 1) == "AF Gain 53%"
        assert yac.gain_control.adjust(yac, root, radio, "en", "r", -1) == "RF Gain 97%"
        power = yac.power_control.prepare(yac, root, radio)
        assert yac.power_control.set_value(yac, radio, power, "33") is None
        assert "power 33 watts" in yac.verify_settings.verify(yac, root, radio, "en")
        print("YAC package check passed. Python and pyserial are bundled.")
        print("Simulated gain and power controls passed.")
        print("Settings and optional logs stay in: " + str(root))
        print("No radio ports were opened.")
        return
    return yac.main()


if __name__ == "__main__":
    sys.exit(main())
