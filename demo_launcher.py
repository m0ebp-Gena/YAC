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
        assert any((root / "rad_cmds").rglob("*")), "Missing radio commands"
        print("YAC package check passed. Python and pyserial are bundled.")
        print("Settings and optional logs stay in: " + str(root))
        print("No radio ports were opened.")
        return
    return yac.main()


if __name__ == "__main__":
    sys.exit(main())
