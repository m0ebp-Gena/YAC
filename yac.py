"""YAC startup: load preferences and establish a radio connection."""

from __future__ import annotations

import configparser
import argparse
import logging
import os
import re
import time
import sys
import tempfile
from pathlib import Path

from modules import lang_sel
from modules.find_rad import RadioConnection, find_radios
from modules.signal_report import format_s_meter
from modules.icom_profile import SUPPORTED_MODELS, load_profile
from modules import verify_settings, gain_control, power_control, filter_control, ts480_control, mic_gain, agc_control
from modules import speech_processor, split_control, antenna_control


DEBUG_LOG = logging.getLogger("yac")
VERSION = "001 beta"
_yaesu_vfo_side = 0  # FTX-1 CAT: 0=MAIN, 1=SUB. Selection lasts this session.
UP_KEY = "."
DOWN_KEY = ","
_ICOM_VFO_SELECTION: dict[tuple[str, int], int] = {}


def _icom_supported(radio: RadioConnection) -> bool:
    return (
        radio.protocol == "CI-V" and radio.civ_address is not None
        and radio.model_id.casefold() in SUPPORTED_MODELS
    )


def _icom_profile(radio: RadioConnection) -> dict:
    return load_profile(project_root(), radio.model_id.casefold())


def _icom_read(radio: RadioConnection, name: str) -> bytes:
    command = _icom_profile(radio)["commands"]["read"][name]
    return _civ_exchange(radio, command[0], command[1] if len(command) > 1 else None)


def _icom_write(radio: RadioConnection, name: str, data: bytes) -> bytes:
    command = _icom_profile(radio)["commands"]["set"][name]
    return _civ_send(radio, command[0], command[1:] + data)


def _icom_select_vfo(root: Path, radio: RadioConnection, language: str) -> str:
    """Select the first VFO/band, then alternate after acknowledgements."""
    key = (radio.port, radio.civ_address)
    selected = 1 - _ICOM_VFO_SELECTION[key] if key in _ICOM_VFO_SELECTION else 0
    response = _icom_write(radio, "vfo_b" if selected else "vfo_a", b"")
    acknowledgement = bytes((0xFE, 0xFE, 0xE0, radio.civ_address, 0xFB, 0xFD))
    if acknowledgement not in response:
        return _read_label(root, language, "l072", "NOT Understood.")
    _ICOM_VFO_SELECTION[key] = selected
    frequency = _current_frequency(root, radio)
    mode = _current_mode(radio)
    if frequency is None or mode is None:
        return _read_label(root, language, "l050", "Could not read frequency and mode from the radio.")
    labels = _icom_profile(radio).get("vfo_labels", ["VFO A", "VFO B"])
    return f"{labels[selected]} {frequency} {mode}"


def _ftx1(radio: RadioConnection) -> bool:
    return radio.protocol == "CAT" and radio.manufacturer_key == "yaesu" and radio.model_id == "0840"


def _yaesu_clarifier(radio: RadioConnection) -> bool:
    return (
        radio.protocol == "CAT" and radio.manufacturer_key == "yaesu"
        and radio.model_id in {"0761", "0840"}
    )


def _configure_debug(root: Path, enabled: bool) -> None:
    """Enable an append-only diagnostic log when requested by the user."""
    if not enabled or DEBUG_LOG.handlers:
        return
    log_directory = root / "logs"
    log_directory.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(log_directory / "yac-debug.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    DEBUG_LOG.addHandler(handler)
    DEBUG_LOG.setLevel(logging.DEBUG)
    DEBUG_LOG.propagate = False
    DEBUG_LOG.info("Debug logging enabled")


def project_root() -> Path:
    return Path(__file__).resolve().parent


def detect_platform() -> str:
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("linux"):
        return "linux"
    return sys.platform.casefold() or "unknown"


def _read_settings(ini_path: Path) -> dict[str, str]:
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str.casefold
    if ini_path.exists():
        with ini_path.open("r", encoding="utf-8-sig") as ini_file:
            parser.read_file(ini_file)
    if not parser.has_section("yac"):
        return {}
    return {key.casefold(): value.strip() for key, value in parser.items("yac")}


def _set_yac_value(ini_path: Path, key: str, value: str) -> None:
    """Update one [yac] value without rewriting radio profiles."""
    contents = ini_path.read_text(encoding="utf-8-sig") if ini_path.exists() else ""
    newline = "\r\n" if "\r\n" in contents else "\n"
    lines = contents.splitlines(keepends=True)
    start: int | None = None
    end = len(lines)
    setting_line: int | None = None
    for index, line in enumerate(lines):
        header = re.match(r"^[ \t]*\[([^\]]+)\]", line.rstrip("\r\n"))
        if header:
            if start is not None:
                end = index
                break
            if header.group(1).strip().casefold() == "yac":
                start = index
                continue
        if start is not None and re.match(
            rf"^[ \t]*{re.escape(key)}[ \t]*=", line.rstrip("\r\n"), re.IGNORECASE
        ):
            setting_line = index

    if start is None:
        if lines and not lines[-1].endswith(("\n", "\r")):
            lines[-1] += newline
        if lines and lines[-1].strip():
            lines.append(newline)
        lines.extend((f"[yac]{newline}", f"{key}={value}{newline}"))
    elif setting_line is not None:
        line = lines[setting_line]
        ending = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
        prefix = re.match(rf"^([ \t]*{re.escape(key)}[ \t]*=[ \t]*)", line, re.IGNORECASE)
        lines[setting_line] = f"{prefix.group(1)}{value}{ending}"
    else:
        insertion = end
        while insertion > start + 1 and not lines[insertion - 1].strip():
            insertion -= 1
        lines.insert(insertion, f"{key}={value}{newline}")

    ini_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="", dir=ini_path.parent,
            prefix=f".{ini_path.name}.", suffix=".tmp", delete=False,
        ) as temporary_file:
            temporary_file.write("".join(lines))
            temporary_path = Path(temporary_file.name)
        os.replace(temporary_path, ini_path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def _ensure_language(root: Path, ini_path: Path, language: str) -> str | None:
    from modules import lang_sel

    if language.casefold() in lang_sel.LANGUAGE_CODES:
        return language.casefold()
    selected = lang_sel.show_language_menu(root)
    if selected is None:
        return None
    lang_sel.set_language(ini_path, selected)
    return selected


def _read_label(root: Path, language: str, label_id: str, fallback: str) -> str:
    try:
        return (root / "lang" / language / "labels" / label_id).read_text(
            encoding="utf-8-sig"
        ).strip()
    except OSError:
        return fallback


def _show_welcome(root: Path, language: str, call: str) -> None:
    name = call.strip() or _read_label(root, language, "l105", "Radio Ham")
    greeting = _read_label(root, language, "l104", "Welcome {name}")
    version = _read_label(root, language, "l106", "Version {version}")
    print(greeting.format(name=name))
    print("Yet Another Controller")
    print(version.format(version=VERSION))
    sys.stdout.flush()


def _choose_radio(
    radios: list[RadioConnection], root: Path, language: str
) -> RadioConnection | None:
    """Use the only discovered radio, or ask which discovered profile to use."""
    from modules import lang_sel

    if not radios:
        return None
    if len(radios) == 1:
        return radios[0]

    print(_read_label(
        root, language, "l026",
        "More than one radio responded. Which profile would you like to use?",
    ))
    for index, radio in enumerate(radios, 1):
        print(f"{index}. {radio.model_name} ({radio.port}, {radio.baudrate} baud)")

    prompt = _read_label(root, language, "l027", "Profile?")
    help_hint = _read_label(root, language, "l074", "h: Help")
    chosen: RadioConnection | None = None
    selection: int | None = None
    while True:
        try:
            print(help_hint)
            print(prompt, flush=True)
            entered = lang_sel.read_key()
        except (EOFError, OSError, RuntimeError):
            break
        if entered.casefold() == "q":
            break
        if entered.casefold() == "h":
            print(_read_label(
                root, language, "l075",
                "Type a number to highlight a profile; press Space to select it, or q to cancel.",
            ))
            continue
        if entered == " ":
            if selection is not None:
                chosen = radios[selection - 1]
                break
            continue
        if not entered.isdigit():
            continue
        new_selection = int(entered)
        if 1 <= new_selection <= len(radios):
            selection = new_selection
            print(f"{selection}. {radios[selection - 1].model_name}")

    for radio in radios:
        if radio is not chosen:
            radio.close()
    return chosen


MODE_LABELS = {
    "1": "LSB", "2": "USB", "3": "CW-U", "4": "FM", "5": "AM",
    "6": "RTTY-L", "7": "CW-L", "8": "DATA-L", "9": "RTTY-U",
    "A": "DATA-FM", "B": "FM-N", "C": "DATA-U", "D": "AM-N",
    "E": "PSK", "F": "DATA-FM-N", "H": "C4FM-DN", "I": "C4FM-VW",
}
KENWOOD_MODE_LABELS = {
    "1": "LSB", "2": "USB", "3": "CW", "4": "FM", "5": "AM",
    "6": "RTTY", "7": "CW-R", "9": "RTTY-R",
}

CTCSS_TONES = (
    "67.0", "69.3", "71.9", "74.4", "77.0", "79.7", "82.5", "85.4",
    "88.5", "91.5", "94.8", "97.4", "100.0", "103.5", "107.2", "110.9",
    "114.8", "118.8", "123.0", "127.3", "131.8", "136.5", "141.3", "146.2",
    "151.4", "156.7", "159.8", "162.2", "165.5", "167.9", "171.3", "173.8",
    "177.3", "179.9", "183.5", "186.2", "189.9", "192.8", "196.6", "199.5",
    "203.5", "206.5", "210.7", "218.1", "225.7", "229.1", "233.6", "241.8",
    "250.3", "254.1",
)
ICOM_DCS_CODES = {
    23, 25, 26, 31, 32, 36, 43, 47, 51, 53, 54, 65, 71, 72, 73, 74, 114,
    115, 116, 122, 125, 131, 132, 134, 143, 145, 152, 155, 156, 162, 165,
    172, 174, 205, 212, 223, 225, 226, 243, 244, 245, 246, 251,
    252, 255, 261, 263, 265, 266, 271, 274, 306, 311, 315, 325, 331, 332,
    343, 346, 351, 356, 364, 365, 371, 411, 412, 413, 423, 431,
    432, 445, 446, 452, 454, 455, 462, 464, 465, 466, 503,
    506, 516, 523, 526, 532, 546, 565, 606, 612, 624, 627, 631, 632, 654,
    662, 664, 703, 712, 723, 731, 732, 734, 743, 754,
}
TS590_CTCSS = (
    "67.0", "69.3", "71.9", "74.4", "77.0", "79.7", "82.5", "85.4", "88.5", "91.5",
    "94.8", "97.4", "100.0", "103.5", "107.2", "110.9", "114.8", "118.8", "123.0",
    "127.3", "131.8", "136.5", "141.3", "146.2", "151.4", "156.7", "162.2", "167.9", "173.8",
    "179.9", "186.2", "192.8", "203.5", "206.5", "210.7", "218.1", "225.7", "229.1",
    "233.6", "241.8", "250.3", "254.1",
)


def _cat_exchange(radio: RadioConnection, command: str) -> str:
    """Send a CAT command and return its semicolon-terminated response."""
    stream = getattr(radio, "_decoder_cat", None)
    if stream is not None:
        return stream.exchange(command)
    serial = radio.serial
    DEBUG_LOG.debug("CAT TX port=%s baud=%s command=%r", radio.port, radio.baudrate, command)
    serial.reset_input_buffer()
    serial.write(command.encode("ascii"))
    serial.flush()
    response = bytearray()
    deadline = time.monotonic() + 0.8
    while time.monotonic() < deadline:
        waiting = getattr(serial, "in_waiting", 0)
        chunk = serial.read(min(waiting, 128) if waiting else 1)
        if chunk:
            response.extend(chunk)
            if b";" in response:
                break
    DEBUG_LOG.debug("CAT RX port=%s bytes=%r", radio.port, bytes(response))
    return response.decode("ascii", errors="ignore").upper()


def _frequency_mhz(digits: str) -> str | None:
    if not digits.isdigit():
        return None
    hz = int(digits)
    if hz <= 0:
        return None
    mhz = f"{hz / 1_000_000:.6f}".rstrip("0").rstrip(".")
    return mhz


def _radio_command_file(root: Path, radio: RadioConnection, group: str, key: str) -> Path | None:
    """Resolve an operation file: model override first, then common default."""
    candidates = (
        root / radio.radio_id_path / group / key,
        root / radio.common_command_path / group / key,
    )
    return next((candidate for candidate in candidates if candidate.is_file()), None)


def _civ_exchange(radio: RadioConnection, command: int, subcommand: int | None = None) -> bytes:
    """Issue one read-only CI-V request and return its response frame."""
    if radio.civ_address is None:
        return b""
    request = bytearray((0xFE, 0xFE, radio.civ_address, 0xE0, command))
    if subcommand is not None:
        request.append(subcommand)
    request.append(0xFD)
    serial = radio.serial
    DEBUG_LOG.debug("CI-V TX port=%s frame=%s", radio.port, request.hex(" ").upper())
    serial.reset_input_buffer()
    serial.write(bytes(request))
    serial.flush()
    response = bytearray()
    deadline = time.monotonic() + 0.8
    while time.monotonic() < deadline:
        waiting = getattr(serial, "in_waiting", 0)
        chunk = serial.read(min(waiting, 128) if waiting else 1)
        if chunk:
            response.extend(chunk)
            acknowledgement = bytes((0xFE, 0xFE, 0xE0, radio.civ_address))
            if (
                _civ_response_data(bytes(response), radio.civ_address, command, subcommand) is not None
                or acknowledgement + b"\xFA\xFD" in response
            ):
                break
    DEBUG_LOG.debug("CI-V RX port=%s frame=%s", radio.port, bytes(response).hex(" ").upper())
    return bytes(response)


def _civ_send(radio: RadioConnection, command: int, data: bytes) -> bytes:
    """Send a CI-V command with a data area and return the radio response."""
    if radio.civ_address is None:
        return b""
    request = bytearray((0xFE, 0xFE, radio.civ_address, 0xE0, command))
    request.extend(data)
    request.append(0xFD)
    serial = radio.serial
    DEBUG_LOG.debug("CI-V TX port=%s frame=%s", radio.port, request.hex(" ").upper())
    serial.reset_input_buffer()
    serial.write(bytes(request))
    serial.flush()
    response = bytearray()
    deadline = time.monotonic() + 0.8
    while time.monotonic() < deadline:
        waiting = getattr(serial, "in_waiting", 0)
        chunk = serial.read(min(waiting, 128) if waiting else 1)
        if chunk:
            response.extend(chunk)
            acknowledgement = bytes((0xFE, 0xFE, 0xE0, radio.civ_address))
            if (
                acknowledgement + b"\xFB\xFD" in response
                or acknowledgement + b"\xFA\xFD" in response
            ):
                break
    DEBUG_LOG.debug("CI-V RX port=%s frame=%s", radio.port, bytes(response).hex(" ").upper())
    return bytes(response)


def _civ_response_data(
    response: bytes, address: int, command: int, subcommand: int | None = None
) -> bytes | None:
    marker = bytes((0xFE, 0xFE, 0xE0, address, command))
    start = response.find(marker)
    if start < 0:
        return None
    start += len(marker)
    if subcommand is not None:
        if start >= len(response) or response[start] != subcommand:
            return None
        start += 1
    end = response.find(b"\xFD", start)
    if end < 0:
        return None
    data = response[start:end]
    if data[:1] in (b"\xFA", b"\xFB"):
        return None
    return data


def _civ_bcd_frequency(data: bytes | None) -> str | None:
    if data is None or len(data) != 5:
        return None
    # CI-V frequency digits are packed BCD and sent least-significant byte first.
    digits = "".join(f"{byte:02X}" for byte in reversed(data))
    if not digits.isdigit():
        return None
    return _frequency_mhz(digits)


def _tone_radio_kind(radio: RadioConnection) -> str | None:
    if radio.protocol == "CI-V" and radio.model_id.casefold() in {"ic-705", "ic-9700"}:
        return "ic9700" if radio.model_id.casefold() == "ic-9700" else "ic705"
    if radio.protocol == "CAT" and radio.manufacturer_key == "yaesu":
        if radio.model_id in {"0761", "0840"}:
            return "ftdx10" if radio.model_id == "0761" else "ftx1"
    if radio.protocol == "CAT" and radio.manufacturer_key == "kenwood" and radio.model_id == "023":
        return "ts590"
    if ts480_control.variant(sys.modules[__name__], radio) is not None:
        return "ts480"
    return None


def _tone_band_supported(kind: str, frequency: str | None) -> bool:
    try:
        hz = int(round(float(frequency or "0") * 1_000_000))
    except ValueError:
        return False
    # Repeater-tone functions are intended for FM VHF/UHF, and 10/6 m on these rigs.
    if kind == "ftdx10":
        return 28_000_000 <= hz <= 29_700_000 or 50_000_000 <= hz <= 54_000_000
    if kind == "ic9700":
        return (144_000_000 <= hz <= 148_000_000
                or 430_000_000 <= hz <= 450_000_000
                or 1_240_000_000 <= hz <= 1_300_000_000)
    if kind == "ts590":
        return 28_000_000 <= hz <= 29_700_000
    if kind == "ts480":
        return (28_000_000 <= hz <= 29_700_000
                or 50_000_000 <= hz <= 54_000_000)
    if kind == "ftx1":
        return (
            28_000_000 <= hz <= 29_700_000
            or 50_000_000 <= hz <= 54_000_000
            or 144_000_000 <= hz <= 148_000_000
            or 430_000_000 <= hz <= 450_000_000
        )
    return (
        28_000_000 <= hz <= 29_700_000
        or 50_000_000 <= hz <= 54_000_000
        or 144_000_000 <= hz <= 148_000_000
        or 420_000_000 <= hz <= 450_000_000
    )


def _tone_value(value: str, allow_dcs: bool, selection: str | None = None) -> tuple[str, str] | None:
    if selection is not None:
        if selection in {"DCS N", "DCS I"}:
            if not allow_dcs or re.fullmatch(r"[0-7]{3}", value) is None:
                return None
            return (selection, value) if int(value) in ICOM_DCS_CODES else None
        if selection != "CTCSS" or re.fullmatch(r"[0-9]{2,3}(?:\.[0-9])?", value) is None:
            return None
        if len(value) > 5:
            return None
        tone = f"{float(value):.1f}"
        return ("CTCSS", tone) if tone in CTCSS_TONES else None
    normalized = value.strip().upper().replace("HZ", "").strip().replace(",", ".")
    if normalized.startswith("D"):
        digits = normalized[1:]
        if not allow_dcs or len(digits) != 3 or not digits.isdigit():
            return None
        code = int(digits)
        if code not in ICOM_DCS_CODES:
            return None
        return "DCS", f"{code:03d}"
    try:
        tone = f"{float(normalized):.1f}"
    except ValueError:
        return None
    if tone not in CTCSS_TONES:
        return None
    return "CTCSS", tone


def _tone_command(
    radio: RadioConnection, kind: str, tone_kind: str, value: str, target: str,
) -> bool:
    """Apply a validated tone to a supported radio; target is TX or Both."""
    if tone_kind == "CTCSS":
        tone_index = CTCSS_TONES.index(value)
        if kind in {"ts590", "ts480"}:
            # TS-590's CN/TN list has 42 entries, with its own numbering.
            if value not in TS590_CTCSS:
                return False
            index = TS590_CTCSS.index(value)
            if target == "TX":
                _cat_exchange(radio, f"TN{index:02d};")
                _cat_exchange(radio, "CT0;")
                _cat_exchange(radio, "TO1;")
                return (
                    f"TN{index:02d};" in _cat_exchange(radio, "TN;")
                    and "CT0;" in _cat_exchange(radio, "CT;")
                    and "TO1;" in _cat_exchange(radio, "TO;")
                )
            _cat_exchange(radio, f"CN{index:02d};")
            _cat_exchange(radio, "TO0;")
            _cat_exchange(radio, "CT1;")
            return (
                f"CN{index:02d};" in _cat_exchange(radio, "CN;")
                and "TO0;" in _cat_exchange(radio, "TO;")
                and "CT1;" in _cat_exchange(radio, "CT;")
            )
        if kind == "ftdx10":
            side = 1 if _yaesu_vfo_side and _ftx1(radio) else 0
            _cat_exchange(radio, f"CN{side}0{tone_index:03d};")
            _cat_exchange(radio, f"CT{side}{2 if target == 'TX' else 1};")
            return (
                re.search(rf"CN{side}0{tone_index:03d};", _cat_exchange(radio, f"CN{side}0;")) is not None
                and re.search(rf"CT{side}{2 if target == 'TX' else 1};", _cat_exchange(radio, f"CT{side};")) is not None
            )
        if kind == "ftx1":
            side = 1 if _yaesu_vfo_side else 0
            _cat_exchange(radio, f"CN{side}0{tone_index:03d};")
            _cat_exchange(radio, f"CT{side}{1 if target == 'TX' else 2};")
            return (
                re.search(rf"CN{side}0{tone_index:03d};", _cat_exchange(radio, f"CN{side}0;")) is not None
                and re.search(rf"CT{side}{1 if target == 'TX' else 2};", _cat_exchange(radio, f"CT{side};")) is not None
            )
        if kind in {"ic705", "ic9700"}:
            ack = bytes((0xFE, 0xFE, 0xE0, radio.civ_address, 0xFB, 0xFD))
            digits = f"{int(round(float(value) * 10)):04d}"
            data = bytes((0x00, int(digits[:2], 16), int(digits[2:], 16)))
            first = _civ_send(radio, 0x1B, bytes((0x00,)) + data)
            second = _civ_send(radio, 0x1B, bytes((0x01,)) + data) if target == "Both" else first
            mode = 0x01 if target == "TX" else 0x02
            third = _civ_send(radio, 0x16, bytes((0x5D, mode)))
            actual = _civ_response_data(_civ_exchange(radio, 0x16, 0x5D), radio.civ_address, 0x16, 0x5D)
            tx = _civ_response_data(_civ_exchange(radio, 0x1B, 0x00), radio.civ_address, 0x1B, 0x00)
            rx = _civ_response_data(_civ_exchange(radio, 0x1B, 0x01), radio.civ_address, 0x1B, 0x01) if target == 'Both' else data
            return ack in first and ack in second and ack in third and actual == bytes((mode,)) and tx == data and rx == data
    else:
        code = int(value)
        code_index = sorted(ICOM_DCS_CODES).index(code)
        inverted = tone_kind == "DCS I"
        if kind == "ftx1":
            if target == "TX":
                return False
            side = 1 if _yaesu_vfo_side else 0
            template = _radio_command_file(project_root(), radio, "set", "dcs_polarity")
            query = _radio_command_file(project_root(), radio, "read", "dcs_polarity")
            if template is None or query is None:
                return False
            # EX menu 01/03/23 and 24: receive and transmit DCS polarity.
            for menu in ("010323", "010324"):
                _cat_exchange(radio, template.read_text(encoding="ascii").strip().format(menu=menu, polarity=int(inverted)))
                answer = _cat_exchange(radio, query.read_text(encoding="ascii").strip().format(menu=menu))
                if f"EX{menu}{int(inverted)};" not in answer:
                    return False
            _cat_exchange(radio, f"CN{side}1{code_index:03d};")
            _cat_exchange(radio, f"CT{side}3;")
            return (
                re.search(rf"CN{side}1{code_index:03d};", _cat_exchange(radio, f"CN{side}1;")) is not None
                and re.search(rf"CT{side}3;", _cat_exchange(radio, f"CT{side};")) is not None
            )
        if kind in {"ic705", "ic9700"}:
            ack = bytes((0xFE, 0xFE, 0xE0, radio.civ_address, 0xFB, 0xFD))
            # 1B 02: TX polarity in the high nibble, RX in the low nibble.
            polarity = 0x11 if inverted else 0x00
            if target == "TX":
                current = _civ_response_data(_civ_exchange(radio, 0x1B, 0x02), radio.civ_address, 0x1B, 0x02)
                if current is None or len(current) != 3:
                    return False
                if current[0] not in {0x00, 0x01, 0x10, 0x11}:
                    return False
                polarity = (current[0] & 0x01) | (0x10 if inverted else 0x00)
            payload = bytes((0x02, polarity, int(value[0]), int(value[1:3], 16)))
            first = _civ_send(radio, 0x1B, payload)
            mode = 0x06 if target == "TX" else 0x03
            second = _civ_send(radio, 0x16, bytes((0x5D, mode)))
            actual = _civ_response_data(_civ_exchange(radio, 0x16, 0x5D), radio.civ_address, 0x16, 0x5D)
            dcs = _civ_response_data(_civ_exchange(radio, 0x1B, 0x02), radio.civ_address, 0x1B, 0x02)
            return ack in first and ack in second and actual == bytes((mode,)) and dcs == payload[1:]
    return False


def _set_tone(
    root: Path, radio: RadioConnection, language: str, raw_value: str, target: str,
    selection: str | None = None,
) -> str:
    kind = _tone_radio_kind(radio)
    if kind is None:
        return _read_label(root, language, "l091", "CTCSS/DCS is not supported for this radio.")
    frequency = _current_frequency(root, radio)
    if _current_mode(radio) != "FM" or not _tone_band_supported(kind, frequency):
        return _read_label(root, language, "l092", "CTCSS/DCS is available only in supported FM repeater bands.")
    selected = _tone_value(raw_value, kind in {"ftx1", "ic705", "ic9700"}, selection)
    if selected is None:
        return _read_label(root, language, "l093", "Invalid tone/code. h: help")
    tone_kind, value = selected
    if kind == "ftx1" and tone_kind != "CTCSS" and target == "TX":
        return _read_label(root, language, "l098", "DCS TX only unavailable. b: Both")
    try:
        success = _tone_command(radio, kind, tone_kind, value, target)
    except Exception:
        DEBUG_LOG.exception("Tone command failed model=%s value=%s target=%s", radio.model_id, value, target)
        success = False
    if not success:
        return _read_label(root, language, "l094", "Tone change failed.")
    target_label = _read_label(root, language, "l103" if target == "Both" else "l102", target)
    return f"{tone_kind} {value}{' Hz' if tone_kind == 'CTCSS' else ''} {target_label}"


def _edit_tone(selection: str, initial: str = "") -> tuple[str, str]:
    """Restricted editable field; i, h and q remain commands while editing."""
    from modules import name_call_sel

    previous_settings = None
    if os.name != "nt":
        if not sys.stdin.isatty():
            raise RuntimeError("Tone entry requires an interactive terminal.")
        import termios
        import tty
        descriptor = sys.stdin.fileno()
        previous_settings = termios.tcgetattr(descriptor)
        tty.setraw(descriptor)
    buffer = list(initial)
    cursor = len(buffer)
    limit = 5 if selection == "CTCSS" else 3
    sys.stdout.write("\n")
    drawn = 0
    try:
        drawn = name_call_sel._draw_input(buffer, cursor, drawn)
        while True:
            key = name_call_sel._read_edit_key()
            if key.casefold() in {"i", "h", "q"} or key == "enter":
                return key.casefold(), "".join(buffer)
            if key == "left":
                cursor = max(0, cursor - 1)
            elif key == "right":
                cursor = min(len(buffer), cursor + 1)
            elif key == "home":
                cursor = 0
            elif key == "end":
                cursor = len(buffer)
            elif key == "backspace":
                if cursor:
                    cursor -= 1
                    del buffer[cursor]
            elif key == "delete":
                if cursor < len(buffer):
                    del buffer[cursor]
            elif len(key) == 1 and len(buffer) < limit:
                if key in "0123456789" or (key == "." and selection == "CTCSS" and "." not in buffer):
                    buffer.insert(cursor, key)
                    cursor += 1
            drawn = name_call_sel._draw_input(buffer, cursor, drawn)
    finally:
        if previous_settings is not None:
            termios.tcsetattr(descriptor, termios.TCSADRAIN, previous_settings)


def _tone_control(root: Path, radio: RadioConnection, language: str, call: str) -> None:
    from modules import chat_int, help_int, lang_sel

    kind = _tone_radio_kind(radio)
    if kind is None:
        chat_int.show_response(_read_label(root, language, "l091", "CTCSS/DCS is not supported for this radio."))
        return
    selections = ("CTCSS", "DCS N", "DCS I") if kind in {"ftx1", "ic705", "ic9700"} else ("CTCSS",)
    labels = {"CTCSS": "l096", "DCS N": "l099", "DCS I": "l100"}
    index = 0
    value = ""
    while True:
        selection = selections[index]
        chat_int.show_response(_read_label(root, language, labels[selection], selection))
        action, value = _edit_tone(selection, value)
        if action == "q":
            chat_int.show_back(root, language)
            chat_int.show_request(call, action)
            return
        if action == "i":
            chat_int.show_request(call, action)
            index = (index + 1) % len(selections)
            value = ""
            continue
        if action == "h":
            chat_int.show_request(call, action)
            chat_int.show_response(help_int.get_help(root, language, "h004"))
            sys.stdout.write("\n")
            continue
        if not value:
            sys.stdout.write("\n")
            continue
        parsed = _tone_value(value, kind in {"ftx1", "ic705", "ic9700"}, selection)
        if parsed is None or (kind in {"ts590", "ts480"} and parsed[1] not in TS590_CTCSS):
            sys.stdout.write("\n")
            chat_int.show_response(_read_label(root, language, "l093", "Invalid tone/code. h: help"))
            sys.stdout.write("\n")
            continue
        sys.stdout.write("\n")
        automatic_both = kind == "ftx1" and selection != "CTCSS"
        while True:
            if automatic_both:
                key = "b"
            else:
                chat_int.show_response(_read_label(root, language, "l101", "TX/Both: t/b"))
                key = lang_sel.read_key().casefold()
            if key not in {"t", "b", "q", "h", "i"}:
                continue
            if not automatic_both:
                chat_int.show_request(call, key)
            if key == "q":
                chat_int.show_back(root, language)
                return
            if key == "h":
                chat_int.show_response(help_int.get_help(root, language, "h004"))
                sys.stdout.write("\n")
                continue
            if key == "i":
                index = (index + 1) % len(selections)
                value = ""
                break
            target = "TX" if key == "t" else "Both"
            response = _set_tone(root, radio, language, value, target, selection)
            chat_int.show_response(response)
            target_label = _read_label(root, language, "l103" if key == "b" else "l102", target)
            expected = f"{selection} {parsed[1]}{' Hz' if selection == 'CTCSS' else ''} {target_label}"
            if response == expected:
                return
            sys.stdout.write("\n")
            break


def _icom_offset_hz(radio: RadioConnection) -> int | None:
    """Read the Icom shared RIT/XIT offset in signed hertz."""
    if radio.civ_address is None:
        return None
    response = _icom_read(radio, "offset")
    data = _civ_response_data(response, radio.civ_address, 0x21, 0x00)
    if data is None or len(data) != 3:
        return None
    if any(value >> 4 > 9 or value & 0x0F > 9 for value in data[:2]):
        return None
    magnitude = int("".join(f"{value:02X}" for value in reversed(data[:2])))
    if data[2] not in (0x00, 0x01):
        return None
    return -magnitude if data[2] == 0x01 else magnitude


def _icom_clarifier_enabled(radio: RadioConnection, subcommand: int) -> bool | None:
    if radio.civ_address is None:
        return None
    if subcommand == 0x02 and not _icom_profile(radio).get("supports_xit", True):
        return False
    response = _icom_read(radio, "rit" if subcommand == 0x01 else "xit")
    data = _civ_response_data(response, radio.civ_address, 0x21, subcommand)
    if data is None or len(data) != 1 or data[0] not in (0x00, 0x01):
        return None
    return bool(data[0])


def _yaesu_offset_state(radio: RadioConnection) -> tuple[int, bool, bool] | None:
    side = _yaesu_vfo_side if _ftx1(radio) else 0
    response = _cat_exchange(radio, f"CF{side}01;")
    match = re.search(rf"CF{side}01([+-])(\d{{4}});", response)
    if not match:
        return None
    magnitude = int(match.group(2))
    offset = -magnitude if match.group(1) == "-" else magnitude
    response = _cat_exchange(radio, f"CF{side}00;")
    match = re.search(rf"CF{side}00([01])([01])000;", response)
    if not match:
        return None
    return offset, match.group(1) == "1", match.group(2) == "1"


def _set_icom_offset(radio: RadioConnection, offset_hz: int) -> None:
    magnitude = abs(offset_hz)
    digits = f"{magnitude:04d}"
    payload = bytes((
        int(digits[2:4], 16),
        int(digits[0:2], 16),
        0x01 if offset_hz < 0 else 0x00,
    ))
    _icom_write(radio, "offset", payload)


def _set_icom_clarifier_enabled(
    radio: RadioConnection, subcommand: int, enabled: bool,
) -> None:
    if subcommand == 0x02 and not _icom_profile(radio).get("supports_xit", True):
        return
    _icom_write(radio, "rit" if subcommand == 0x01 else "xit", bytes((int(enabled),)))


def _set_yaesu_offset(radio: RadioConnection, offset_hz: int) -> None:
    side = _yaesu_vfo_side if _ftx1(radio) else 0
    sign = "-" if offset_hz < 0 else "+"
    _cat_exchange(radio, f"CF{side}01{sign}{abs(offset_hz):04d};")


def _zero_offsets(radio: RadioConnection) -> bool:
    """Start a clarifier adjustment session with receive and transmit at zero."""
    if radio.protocol == "CAT" and radio.model_id == "020":
        return ts480_control.zero_offsets(sys.modules[__name__], radio)
    if _icom_supported(radio):
        _set_icom_offset(radio, 0)
        return _icom_offset_hz(radio) == 0
    if radio.protocol == "CAT" and radio.manufacturer_key == "yaesu":
        state = _yaesu_offset_state(radio)
        if state is None:
            return False
        _set_yaesu_offset(radio, 0)
        actual = _yaesu_offset_state(radio)
        return actual is not None and actual[0] == 0
    return False


def _set_yaesu_clarifier_state(
    radio: RadioConnection, receive: bool, transmit: bool,
) -> None:
    side = _yaesu_vfo_side if _ftx1(radio) else 0
    _cat_exchange(radio, f"CF{side}00{int(receive)}{int(transmit)}000;")


def _civ_frequency_bytes(hz: int) -> bytes:
    """Encode a CI-V frequency as five little-endian packed BCD bytes."""
    digits = f"{hz:010d}"
    return bytes(int(digits[index:index + 2], 16) for index in range(8, -1, -2))


def _icom_band_mode(hz: int) -> int:
    """Choose a useful default mode from the requested HF/VHF/UHF segment."""
    mhz = hz / 1_000_000
    # Requested HF convention: 160 m through 30 m LSB, 20 m through 6 m USB.
    if mhz < 14:
        return 0x00  # LSB
    if 50 <= mhz <= 54:
        # Region 1 FM/DV gateways, repeater and simplex channel segments.
        if 50.540 <= mhz < 50.580 or 50.700 <= mhz < 50.900 \
                or 51.200 <= mhz < 51.400 \
                or 51.410 <= mhz < 51.600 or 51.810 <= mhz < 52.000:
            return 0x05  # FM
        return 0x01  # USB for SSB/all-mode portions and 52 MHz+ default
    if 144 <= mhz <= 146:
        # Weak-signal and satellite sections are USB; the channelized voice
        # sections from 144.975 through 145.806 MHz use FM/DV.
        return 0x05 if 144.975 <= mhz < 145.806 else 0x01
    if 430 <= mhz <= 440:
        # Region 1 FM voice channels; weak-signal and satellite sections use USB.
        if 433.000 <= mhz < 433.588 or 434.600 <= mhz < 434.988 \
                or 438.000 <= mhz <= 440.000:
            return 0x05
        return 0x01
    return 0x01


# Preserve the last tuned frequency and mode for each Icom band during this run.
_ICOM_BAND_SETTINGS: dict[tuple, tuple[int, int, int | None]] = {}
AMATEUR_BANDS = (
    (1.8, 2.0, "l010", "160M"), (3.5, 4.0, "l011", "80M"),
    (5.25, 5.45, "l012", "60M"), (7.0, 7.3, "l013", "40M"),
    (10.1, 10.15, "l014", "30M"), (14.0, 14.35, "l015", "20M"),
    (18.068, 18.168, "l016", "17M"), (21.0, 21.45, "l017", "15M"),
    (24.89, 24.99, "l018", "12M"), (28.0, 29.7, "l019", "10M"),
    (50.0, 54.0, "l020", "6M"), (70.0, 71.0, "l021", "4M"),
    (108.0, 137.0, "l064", "Air"), (144.0, 148.0, "l022", "2M"),
    (420.0, 450.0, "l023", "70CM"),
    (1240.0, 1300.0, "l024", "23CM"),
)
SHORT_MODE_LABELS = {
    "CW-U": "CWU", "CW-L": "CWL", "RTTY-L": "RTTYL", "RTTY-U": "RTTYU",
    "DATA-L": "DATAL", "DATA-U": "DATAU", "DATA-FM": "DATAFM",
    "DATA-FM-N": "DATAFMN", "FM-N": "FMN", "AM-N": "AMN",
    "CW-R": "CWR", "RTTY-R": "RTTYR",
    "C4FM-DN": "C4FMDN", "C4FM-VW": "C4FMVW",
}
STEP_SIZE_DEFAULTS = {
    "step_ssb": 1000,
    "step_am": 2500,
    "step_fm": 12500,
    "step_cw": 500,
}


def _step_size_key(mode: str | None) -> tuple[str, str] | None:
    """Map a reported radio mode to YAC's user-configured tuning increment."""
    if mode in {
        "LSB", "USB", "RTTY", "RTTYR", "RTTYL", "RTTYU", "DATAL", "DATAU", "PSK",
    }:
        return "step_ssb", "SSB"
    if mode in {"CW", "CWU", "CWL", "CWR"}:
        return "step_cw", "CW"
    if mode in {"AM", "AMN"}:
        return "step_am", "AM"
    if mode in {
        "FM", "FMN", "DATAFM", "DATAFMN", "C4FMDN", "C4FMVW",
        "DV", "WFM",
    }:
        return "step_fm", "FM"
    return None


def _step_frequency(
    root: Path, radio: RadioConnection, language: str,
    settings: dict[str, str], direction: int,
) -> str:
    """Tune one YAC-configured step and verify the radio's frequency readback."""
    step_profile = _step_size_key(_current_mode(radio))
    if step_profile is None:
        return _read_label(root, language, "l072", "NOT Understood.")
    setting_key, _mode_name = step_profile
    try:
        step_hz = int(settings.get(setting_key, STEP_SIZE_DEFAULTS[setting_key]))
    except (TypeError, ValueError):
        step_hz = STEP_SIZE_DEFAULTS[setting_key]
    if step_hz <= 0:
        step_hz = STEP_SIZE_DEFAULTS[setting_key]
    current_frequency = _current_frequency(root, radio)
    if current_frequency is None:
        return _read_label(root, language, "l066", "Could not read current frequency; change cancelled.")
    target_hz = round(float(current_frequency) * 1_000_000) + direction * step_hz
    if not 0 < target_hz <= 1_000_000_000:
        return _read_label(root, language, "l052", "Frequency is outside the supported range.")
    target_frequency = f"{target_hz // 1_000_000}.{target_hz % 1_000_000:06d}"
    return _set_frequency(
        root, radio, language, target_frequency, current_frequency,
    )


def _offset_label(root: Path, language: str, selection: int) -> str:
    label_id = ("l076", "l077", "l078")[selection]
    fallback = ("Receive", "Transmit", "Clear")[selection]
    return _read_label(root, language, label_id, fallback)


def _offset_action(
    root: Path, radio: RadioConnection, language: str,
    selection: int, direction: int,
) -> str:
    if radio.protocol == "CAT" and radio.model_id == "020":
        return ts480_control.offset(sys.modules[__name__], root, radio, language, selection, direction)
    """Adjust the selected clarifier by 10 Hz, or clear both offsets."""
    icom = _icom_supported(radio)
    yaesu = _yaesu_clarifier(radio)
    if not (icom or yaesu):
        return _read_label(root, language, "l072", "NOT Understood.")

    if icom and selection == 1 and not _icom_profile(radio).get("supports_xit", True):
        return _read_label(root, language, "l108", "Transmit offset is not supported for this radio.")
    if icom:
        current_offset = _icom_offset_hz(radio)
        receive_enabled = _icom_clarifier_enabled(radio, 0x01)
        transmit_enabled = _icom_clarifier_enabled(radio, 0x02)
    else:
        current_state = _yaesu_offset_state(radio)
        if current_state is None:
            current_offset = None
            receive_enabled = transmit_enabled = None
        else:
            current_offset, receive_enabled, transmit_enabled = current_state
    if current_offset is None or receive_enabled is None or transmit_enabled is None:
        return _read_label(root, language, "l084", "Could not read the offset setting.")

    if selection == 2:
        if icom:
            _set_icom_offset(radio, 0)
            _set_icom_clarifier_enabled(radio, 0x01, False)
            _set_icom_clarifier_enabled(radio, 0x02, False)
            verified = (
                _icom_offset_hz(radio) == 0
                and _icom_clarifier_enabled(radio, 0x01) is False
                and _icom_clarifier_enabled(radio, 0x02) is False
            )
        else:
            _set_yaesu_offset(radio, 0)
            _set_yaesu_clarifier_state(radio, False, False)
            verified_state = _yaesu_offset_state(radio)
            verified = verified_state == (0, False, False)
        return (
            _offset_label(root, language, 2)
            if verified else _read_label(root, language, "l085", "Offset change failed.")
        )

    target_offset = current_offset + direction * 10
    if not -9990 <= target_offset <= 9990:
        return _read_label(root, language, "l086", "Offset limit reached.")
    if icom:
        _set_icom_offset(radio, target_offset)
        if _icom_offset_hz(radio) != target_offset:
            return _read_label(root, language, "l085", "Offset change failed.")
        _set_icom_clarifier_enabled(
            radio, 0x01 if selection == 0 else 0x02, True,
        )
        actual_offset = _icom_offset_hz(radio)
        actual_enabled = _icom_clarifier_enabled(
            radio, 0x01 if selection == 0 else 0x02,
        )
    else:
        _set_yaesu_offset(radio, target_offset)
        state_after_offset = _yaesu_offset_state(radio)
        if state_after_offset is None or state_after_offset[0] != target_offset:
            return _read_label(root, language, "l085", "Offset change failed.")
        _set_yaesu_clarifier_state(
            radio,
            True if selection == 0 else receive_enabled,
            True if selection == 1 else transmit_enabled,
        )
        actual_state = _yaesu_offset_state(radio)
        actual_offset = actual_state[0] if actual_state else None
        actual_enabled = (
            actual_state[1 if selection == 0 else 2] if actual_state else None
        )
    if actual_offset != target_offset or actual_enabled is not True:
        return _read_label(root, language, "l085", "Offset change failed.")

    hz_label = _read_label(root, language, "l081", "Hertz")
    if target_offset == 0:
        value = _read_label(root, language, "l087", "Zero")
        return f"{_offset_label(root, language, selection)} {value} {hz_label}"
    sign_label = _read_label(
        root, language, "l079" if target_offset > 0 else "l080",
        "Plus" if target_offset > 0 else "Minus",
    )
    return f"{_offset_label(root, language, selection)} {sign_label} {abs(target_offset)} {hz_label}"


def _round_frequency_to_khz(
    root: Path, radio: RadioConnection, language: str,
) -> str:
    """Round the underlying VFO frequency, leaving clarifier offsets intact."""
    restore_clarifiers: tuple[bool, bool] | None = None
    if _icom_supported(radio):
        receive = _icom_clarifier_enabled(radio, 0x01)
        transmit = _icom_clarifier_enabled(radio, 0x02)
        if receive is None or transmit is None:
            return _read_label(root, language, "l084", "Could not read the offset setting.")
        restore_clarifiers = (receive, transmit)
        if receive:
            _set_icom_clarifier_enabled(radio, 0x01, False)
        if transmit:
            _set_icom_clarifier_enabled(radio, 0x02, False)
        if (
            _icom_clarifier_enabled(radio, 0x01) is not False
            or _icom_clarifier_enabled(radio, 0x02) is not False
        ):
            for subcommand, enabled in ((0x01, receive), (0x02, transmit)):
                if enabled:
                    _set_icom_clarifier_enabled(radio, subcommand, True)
            return _read_label(root, language, "l085", "Offset change failed.")
    elif _yaesu_clarifier(radio):
        state = _yaesu_offset_state(radio)
        if state is None:
            return _read_label(root, language, "l084", "Could not read the offset setting.")
        restore_clarifiers = (state[1], state[2])
        if state[1] or state[2]:
            _set_yaesu_clarifier_state(radio, False, False)
            disabled_state = _yaesu_offset_state(radio)
            if disabled_state is None or disabled_state[1:] != (False, False):
                _set_yaesu_clarifier_state(radio, state[1], state[2])
                return _read_label(root, language, "l085", "Offset change failed.")

    result = _read_label(root, language, "l085", "Frequency change failed.")
    try:
        current_frequency = _current_frequency(root, radio)
        if current_frequency is None:
            result = _read_label(root, language, "l066", "Could not read current frequency; change cancelled.")
        else:
            current_hz = round(float(current_frequency) * 1_000_000)
            target_hz = ((current_hz + 500) // 1_000) * 1_000
            if target_hz == current_hz:
                result = current_frequency
            else:
                target_frequency = f"{target_hz // 1_000_000}.{target_hz % 1_000_000:06d}"
                result = _set_frequency(
                    root, radio, language, target_frequency, current_frequency,
                )
    finally:
        if restore_clarifiers is not None:
            receive, transmit = restore_clarifiers
            if _icom_supported(radio):
                _set_icom_clarifier_enabled(radio, 0x01, receive)
                _set_icom_clarifier_enabled(radio, 0x02, transmit)
                restored = (
                    _icom_clarifier_enabled(radio, 0x01) is receive
                    and _icom_clarifier_enabled(radio, 0x02) is transmit
                )
            else:
                _set_yaesu_clarifier_state(radio, receive, transmit)
                state = _yaesu_offset_state(radio)
                restored = state is not None and state[1:] == (receive, transmit)
            if not restored:
                DEBUG_LOG.error("Could not restore clarifier state after frequency rounding")
                result = _read_label(root, language, "l085", "Offset change failed.")
    return result


def _icom_band_change(radio: RadioConnection, direction: int) -> bool:
    """Move bands, restoring the last frequency and mode used this run."""
    centers = _icom_profile(radio)["bands_hz"]
    response = _icom_read(radio, "frequency")
    current = _civ_bcd_frequency(
        _civ_response_data(response, radio.civ_address, 0x03)
    )
    if current is None:
        return False
    current_hz = round(float(current) * 1_000_000)
    index = min(
        range(len(centers)),
        key=lambda candidate: abs(centers[candidate] - current_hz),
    )
    next_index = max(0, min(len(centers) - 1, index + direction))
    if next_index == index:
        return False
    radio_key = (
        radio.port, radio.civ_address, radio.model_id.casefold(),
        _ICOM_VFO_SELECTION.get((radio.port, radio.civ_address), -1),
    )
    mode_data = _civ_response_data(_icom_read(radio, "mode"), radio.civ_address, 0x04)
    if not mode_data or mode_data[0] not in _icom_profile(radio)["modes"]:
        return False
    current_mode = mode_data[0]
    current_filter = mode_data[1] if len(mode_data) > 1 else None
    _ICOM_BAND_SETTINGS[(*radio_key, index)] = (current_hz, current_mode, current_filter)
    saved_setting = _ICOM_BAND_SETTINGS.get((*radio_key, next_index))
    if saved_setting:
        target_hz, target_mode, target_filter = saved_setting
    else:
        target_hz = centers[next_index]
        target_mode = _icom_band_mode(target_hz)
        target_filter = None
    acknowledgement = bytes((0xFE, 0xFE, 0xE0, radio.civ_address, 0xFB, 0xFD))
    def apply(hz: int, mode: int, filter_number: int | None) -> bool:
        response = _icom_write(radio, "e", _civ_frequency_bytes(hz))
        if acknowledgement not in response:
            return False
        frequency = _current_frequency(project_root(), radio)
        if frequency is None or round(float(frequency) * 1_000_000) != hz:
            return False
        # Omitting the filter selects the radio's default for a new band;
        # returning to a remembered band restores its previous filter.
        payload = bytes((mode,)) + (bytes((filter_number,)) if filter_number is not None else b"")
        response = _icom_write(radio, "m", payload)
        actual_mode = _civ_response_data(_icom_read(radio, "mode"), radio.civ_address, 0x04)
        return (
            acknowledgement in response and bool(actual_mode) and actual_mode[0] == mode
            and (filter_number is None or actual_mode[1:2] == bytes((filter_number,)))
        )
    try:
        if apply(target_hz, target_mode, target_filter):
            return True
    except Exception:
        DEBUG_LOG.exception("Icom band change failed port=%s", radio.port)
    try:
        restored = apply(current_hz, current_mode, current_filter)
        DEBUG_LOG.warning("Icom band change rejected; previous settings restored=%s", restored)
    except Exception:
        DEBUG_LOG.exception("Could not restore Icom band settings port=%s", radio.port)
    return False


def _current_frequency(root: Path, radio: RadioConnection) -> str | None:
    """Read and format the active VFO frequency for a supported radio."""
    if _icom_supported(radio):
        response = _icom_read(radio, "frequency")
        return _civ_bcd_frequency(
            _civ_response_data(response, radio.civ_address, 0x03)
        )
    if radio.protocol == "CAT" and radio.manufacturer_key == "yaesu":
        command = "FB;" if _ftx1(radio) and _yaesu_vfo_side else "FA;"
        response = _cat_exchange(radio, command)
        prefix = command[:2]
        match = re.search(rf"{prefix}(\d{{5,11}});", response)
        return _frequency_mhz(match.group(1)) if match else None
    if radio.protocol == "CAT" and radio.manufacturer_key == "kenwood":
        side = ts480_control.vfo(sys.modules[__name__], radio) if radio.model_id == "020" else '0'
        if side is None:
            return None
        prefix = 'FB' if side == '1' else 'FA'
        response = _cat_exchange(radio, prefix + ';')
        match = re.search(rf"{prefix}(\d{{11}});", response)
        return _frequency_mhz(match.group(1)) if match else None
    return None


def _current_mode(radio: RadioConnection) -> str | None:
    """Read the active mode and return its short spoken/display form."""
    if _icom_supported(radio):
        response = _icom_read(radio, "mode")
        data = _civ_response_data(response, radio.civ_address, 0x04)
        mode = _icom_profile(radio)["modes"].get(data[0]) if data else None
    elif radio.protocol == "CAT" and radio.manufacturer_key == "yaesu":
        side = _yaesu_vfo_side if _ftx1(radio) else 0
        response = _cat_exchange(radio, f"MD{side};")
        match = re.search(rf"MD{side}([0-9A-FHI]);", response)
        mode = MODE_LABELS.get(match.group(1)) if match else None
    elif radio.protocol == "CAT" and radio.manufacturer_key == "kenwood":
        response = _cat_exchange(radio, "MD;")
        match = re.search(r"MD([0-9]);", response)
        mode = KENWOOD_MODE_LABELS.get(match.group(1)) if match else None
    else:
        mode = None
    if mode is None:
        return None
    return SHORT_MODE_LABELS.get(mode, mode.replace("-", ""))


def _current_mode_code(radio: RadioConnection) -> int | str | None:
    if _icom_supported(radio):
        response = _icom_read(radio, "mode")
        data = _civ_response_data(response, radio.civ_address, 0x04)
        return data[0] if data and data[0] in _icom_profile(radio)["modes"] else None
    if radio.protocol == "CAT" and radio.manufacturer_key == "yaesu":
        side = _yaesu_vfo_side if _ftx1(radio) else 0
        response = _cat_exchange(radio, f"MD{side};")
        match = re.search(rf"MD{side}([0-9A-FHI]);", response)
        return match.group(1) if match else None
    if radio.protocol == "CAT" and radio.manufacturer_key == "kenwood":
        response = _cat_exchange(radio, "MD;")
        match = re.search(r"MD([0-9]);", response)
        return match.group(1) if match and match.group(1) in KENWOOD_MODE_LABELS else None
    return None


def _available_modes(radio: RadioConnection) -> list[tuple[int | str, str]]:
    if _icom_supported(radio):
        modes = list(_icom_profile(radio)["modes"].items())
        if radio.model_id.casefold() == "ic-9700":
            frequency = _current_frequency(project_root(), radio)
            satellite = _civ_response_data(
                _civ_exchange(radio, 0x16, 0x5A), radio.civ_address, 0x16, 0x5A,
            ) if frequency is not None and float(frequency) >= 1240 else None
            if frequency is None or float(frequency) < 1240 or satellite != b"\x00":
                modes = [(code, label) for code, label in modes if code != 0x22]
        return modes
    if radio.protocol == "CAT" and radio.manufacturer_key == "yaesu":
        modes = MODE_LABELS.items()
        if not _ftx1(radio):
            modes = ((code, label) for code, label in modes if code not in {"H", "I"})
        return [(code, label) for code, label in modes]
    if radio.protocol == "CAT" and radio.manufacturer_key == "kenwood":
        return list(KENWOOD_MODE_LABELS.items())
    return []


def _set_mode(radio: RadioConnection, mode_code: int | str) -> bool:
    if _icom_supported(radio):
        if mode_code not in dict(_available_modes(radio)):
            return False
        response = _icom_write(radio, "m", bytes((int(mode_code),)))
        acknowledgement = bytes((0xFE, 0xFE, 0xE0, radio.civ_address, 0xFB, 0xFD))
        if acknowledgement not in response:
            return False
    elif radio.protocol == "CAT" and radio.manufacturer_key == "yaesu":
        side = _yaesu_vfo_side if _ftx1(radio) else 0
        _cat_exchange(radio, f"MD{side}{mode_code};")
    elif radio.protocol == "CAT" and radio.manufacturer_key == "kenwood":
        _cat_exchange(radio, f"MD{mode_code};")
    else:
        return False
    return _current_mode_code(radio) == mode_code


def _mode_name(radio: RadioConnection, mode_code: int | str) -> str:
    if _icom_supported(radio):
        mode = _icom_profile(radio)["modes"][int(mode_code)]
    elif radio.protocol == "CAT" and radio.manufacturer_key == "kenwood":
        mode = KENWOOD_MODE_LABELS[str(mode_code)]
    else:
        mode = MODE_LABELS[str(mode_code)]
    return SHORT_MODE_LABELS.get(mode, mode.replace('-', ''))


def _band_name(root: Path, language: str, frequency: str) -> str:
    try:
        mhz = float(frequency)
    except ValueError:
        return "?"
    for lower, upper, label_id, short_label in AMATEUR_BANDS:
        if lower <= mhz <= upper:
            return _read_label(root, language, label_id, short_label)
    return "?"


def _band_status(root: Path, language: str, frequency: str, mode: str | None) -> str:
    """Format compact band, frequency, and mode status for chat_int."""
    template = _read_label(root, language, "l060", "{band} {frequency} {mode}")
    return template.format(
        band=_band_name(root, language, frequency), frequency=frequency, mode=mode or "?",
    )


def _band_change(root: Path, radio: RadioConnection, language: str, direction: int) -> str:
    direction_name = "up" if direction > 0 else "down"
    DEBUG_LOG.info(
        "Band request direction=%s model=%s protocol=%s port=%s baud=%s",
        direction_name, radio.model_name, radio.protocol, radio.port, radio.baudrate,
    )
    if _icom_supported(radio):
        if _icom_band_change(radio, direction):
            frequency = _current_frequency(root, radio)
            if frequency:
                mode = _current_mode(radio)
                DEBUG_LOG.info("Band change succeeded direction=%s frequency_mhz=%s mode=%s", direction_name, frequency, mode)
                return _band_status(root, language, frequency, mode)
            DEBUG_LOG.warning("Icom acknowledged band change but frequency readback failed")
            return _read_label(root, language, "l062", "Band changed, but the current frequency could not be read.")
        DEBUG_LOG.warning("Icom band change failed (frequency query, boundary, or missing CI-V ACK)")
        return _read_label(root, language, "l061", "Could not change the band.")
    if radio.protocol == "CAT" and radio.manufacturer_key == "kenwood":
        if radio.model_id == "020" and ts480_control.variant(sys.modules[__name__], radio) is None:
            return _read_label(root, language, "l129", "Not supported")
        command_path = _radio_command_file(root, radio, "set", "b")
        current_frequency = _current_frequency(root, radio)
        if command_path is None or current_frequency is None:
            return _read_label(root, language, "l057", "No verified band-change profile is available for this radio.")
        try:
            profile: dict[str, str] = {}
            for line in command_path.read_text(encoding="ascii").splitlines():
                key, value = line.split("=", 1)
                profile[key.strip().casefold()] = value.strip()
            bands = [
                (int(entry.split(":", 1)[0]), int(entry.split(":", 1)[1]))
                for entry in profile["bands"].split(",")
            ]
            current_hz = round(float(current_frequency) * 1_000_000)
            current_index = min(
                range(len(bands)),
                key=lambda index: abs(bands[index][1] - current_hz),
            )
            target_index = max(0, min(len(bands) - 1, current_index + direction))
            if target_index == current_index:
                return _band_status(root, language, current_frequency, _current_mode(radio))
            command_template = profile["up" if direction > 0 else "down"]
            command = command_template.format(band=f"{bands[target_index][0]:02d}")
        except (OSError, ValueError, KeyError, IndexError):
            DEBUG_LOG.exception("Could not load Kenwood band-change profile from %s", command_path)
            return _read_label(root, language, "l061", "Could not change the band.")
        _cat_exchange(radio, command if command.endswith(";") else command + ";")
        frequency = _current_frequency(root, radio)
        if frequency:
            mode = _current_mode(radio)
            actual_hz = round(float(frequency) * 1_000_000)
            actual_index = min(
                range(len(bands)),
                key=lambda index: abs(bands[index][1] - actual_hz),
            )
            if actual_index == target_index:
                DEBUG_LOG.info("Kenwood band change succeeded direction=%s frequency_mhz=%s mode=%s", direction_name, frequency, mode)
                return _band_status(root, language, frequency, mode)
        DEBUG_LOG.warning("Kenwood band command did not reach the requested band index=%s", target_index)
        return _read_label(root, language, "l061", "Could not change the band.")
    if radio.protocol == "CAT" and radio.manufacturer_key == "yaesu":
        command_path = _radio_command_file(root, radio, "set", "b")
        if command_path is None:
            return _read_label(root, language, "l057", "No verified band-change profile is available for this radio.")
        try:
            commands = {}
            for line in command_path.read_text(encoding="ascii").splitlines():
                key, value = line.split("=", 1)
                commands[key.strip().casefold()] = value.strip()
            command = commands["up" if direction > 0 else "down"]
            if _ftx1(radio):
                command = re.sub(r"(?<=BU|BD)\d(?=;?$)", str(_yaesu_vfo_side), command)
        except (OSError, ValueError, KeyError):
            DEBUG_LOG.exception("Could not load Yaesu band-change command from %s", command_path)
            return _read_label(root, language, "l061", "Could not change the band.")
        _cat_exchange(radio, command if command.endswith(";") else command + ";")
        frequency = _current_frequency(root, radio)
        if frequency:
            mode = _current_mode(radio)
            DEBUG_LOG.info("Band change sent direction=%s frequency_mhz=%s mode=%s", direction_name, frequency, mode)
            return _band_status(root, language, frequency, mode)
        DEBUG_LOG.warning("Yaesu band command sent, but frequency readback failed")
        return _read_label(root, language, "l062", "Band changed, but the current frequency could not be read.")
    DEBUG_LOG.warning("No band-change handler for protocol=%s model=%s", radio.protocol, radio.model_id)
    return _read_label(root, language, "l057", "No verified band-change profile is available for this radio.")


def _civ_bcd_value(data: bytes | None) -> str | None:
    if not data or any(value >> 4 > 9 or value & 0x0F > 9 for value in data):
        return None
    return str(int("".join(f"{value:02X}" for value in data)))


def _icom_status(root: Path, radio: RadioConnection, language: str, command_path: Path) -> str:
    try:
        spec = {}
        for line in command_path.read_text(encoding="ascii").splitlines():
            key, value = line.split("=", 1)
            spec[key.strip().casefold()] = value.strip()
        frequency_command = int(spec["frequency"], 16)
        mode_command = int(spec["mode"], 16)
        signal_bytes = bytes.fromhex(spec["signal"])
        if len(signal_bytes) != 2:
            raise ValueError("signal spec must contain command and subcommand")
    except (OSError, ValueError, KeyError):
        return _read_label(root, language, "l056", "Could not read the radio status command file.")

    frequency_response = _civ_exchange(radio, frequency_command)
    mode_response = _civ_exchange(radio, mode_command)
    signal_response = _civ_exchange(radio, signal_bytes[0], signal_bytes[1])
    frequency = _civ_bcd_frequency(
        _civ_response_data(frequency_response, radio.civ_address, frequency_command)
    )
    mode_data = _civ_response_data(mode_response, radio.civ_address, mode_command)
    signal_data = _civ_response_data(
        signal_response, radio.civ_address, signal_bytes[0], signal_bytes[1]
    )
    mode = None
    if mode_data:
        mode = _icom_profile(radio)["modes"].get(mode_data[0], "?")
    signal_raw = _civ_bcd_value(signal_data)
    if frequency and mode and signal_raw is not None:
        signal = format_s_meter(int(signal_raw), radio.model_id)
        return f"{signal} {frequency} {SHORT_MODE_LABELS.get(mode, mode.replace('-', ''))}"
    return _read_label(root, language, "l050", "Could not read frequency and mode from the radio.")


def _set_frequency(
    root: Path, radio: RadioConnection, language: str, value: str,
    original_frequency: str | None = None,
) -> str:
    try:
        mhz = float(value)
        hz = round(mhz * 1_000_000)
    except (ValueError, OverflowError):
        return _read_label(root, language, "l051", "Enter a frequency in MHz, for example 7.159.")

    if radio.protocol == "CAT" and radio.manufacturer_key == "yaesu":
        minimum_hz = 30_000
        maximum_hz = 75_000_000 if radio.model_id == "0761" else 470_000_000 if radio.model_id == "0840" else 0
    elif radio.protocol == "CAT" and radio.manufacturer_key == "kenwood" and radio.model_id in {"023", "020"}:
        minimum_hz, maximum_hz = 30_000, 60_000_000
    elif _icom_supported(radio):
        profile = _icom_profile(radio)
        minimum_hz, maximum_hz = profile["minimum_hz"], profile["maximum_hz"]
    else:
        return _read_label(root, language, "l057", "No verified frequency-setting profile is available for this radio.")

    if maximum_hz == 0:
        return _read_label(root, language, "l057", "No verified frequency-setting profile is available for this radio.")
    ranges = _icom_profile(radio).get("frequency_ranges_hz", [[minimum_hz, maximum_hz]]) if _icom_supported(radio) else [[minimum_hz, maximum_hz]]
    if not any(low <= hz <= high for low, high in ranges):
        return _read_label(root, language, "l052", "Frequency is outside the supported range.")

    original_frequency = original_frequency or _current_frequency(root, radio)
    if original_frequency is None:
        return _read_label(
            root, language, "l066",
            "Could not read current frequency; change cancelled.",
        )
    original_hz = round(float(original_frequency) * 1_000_000)
    command_attempted = False
    command_acknowledged = True
    cat_command: str | None = None

    if radio.protocol == "CI-V":
        if radio.civ_address is None:
            return _read_label(root, language, "l057", "No verified frequency-setting profile is available for this radio.")
        command_attempted = True
        acknowledgement = bytes((0xFE, 0xFE, 0xE0, radio.civ_address, 0xFB, 0xFD))
        try:
            response = _icom_write(radio, "e", _civ_frequency_bytes(hz))
            if acknowledgement not in response:
                DEBUG_LOG.warning("Icom frequency set did not receive CI-V ACK for %s Hz", hz)
                command_acknowledged = False
        except Exception:
            DEBUG_LOG.exception("Icom frequency command failed port=%s", radio.port)
            command_acknowledged = False
    else:
        template_path = _radio_command_file(root, radio, "set", "e")
        if template_path is None:
            return _read_label(root, language, "l053", "Could not read the radio command file.")
        try:
            template = template_path.read_text(encoding="ascii").strip()
        except OSError:
            return _read_label(root, language, "l053", "Could not read the radio command file.")
        if radio.manufacturer_key == "kenwood":
            if radio.model_id == "020":
                side = ts480_control.vfo(sys.modules[__name__], radio)
                if side is None:
                    return _read_label(root, language, "l066", "")
                template = re.sub(r'^FA', 'FB' if side == '1' else 'FA', template)
            digits = f"{hz:011d}"
            cat_command = re.sub(r"\?{11}", digits, template, count=1)
        else:
            digits = f"{hz:09d}"
            if _ftx1(radio) and _yaesu_vfo_side:
                template = re.sub(r"^FA", "FB", template, count=1)
            cat_command = re.sub(r"\?{9}", digits, template, count=1)
        if cat_command == template:
            return _read_label(root, language, "l054", "The frequency command template is invalid.")
        command_attempted = True
        try:
            _cat_exchange(radio, cat_command)
        except Exception:
            DEBUG_LOG.exception("CAT frequency command failed port=%s", radio.port)

    try:
        actual_frequency = _current_frequency(root, radio)
    except Exception:
        DEBUG_LOG.exception("Could not read frequency after setting port=%s", radio.port)
        actual_frequency = None
    verified = (
        actual_frequency is not None
        and abs(round(float(actual_frequency) * 1_000_000) - hz) <= (0 if _icom_supported(radio) else 10)
        and command_acknowledged
    )
    if not verified:
        DEBUG_LOG.warning("Frequency set readback mismatch requested_hz=%s actual_mhz=%s", hz, actual_frequency)
        restored = not command_attempted
        if command_attempted:
            try:
                if radio.protocol == "CI-V":
                    restore_response = _icom_write(
                        radio, "e", _civ_frequency_bytes(original_hz)
                    )
                    restore_ack = bytes((
                        0xFE, 0xFE, 0xE0, radio.civ_address, 0xFB, 0xFD
                    ))
                    restored = restore_ack in restore_response
                elif cat_command is not None and radio.manufacturer_key == "kenwood":
                    restore_digits = f"{original_hz:011d}"
                    restore_command = re.sub(r"\?{11}", restore_digits, template, count=1)
                    _cat_exchange(radio, restore_command)
                    restored = True
                elif cat_command is not None:
                    restore_digits = f"{original_hz:09d}"
                    restore_command = re.sub(
                        r"\?{9}", restore_digits,
                        template, count=1,
                    )
                    _cat_exchange(radio, restore_command)
                    restored = True
                restored_frequency = _current_frequency(root, radio)
                restored = (
                    restored
                    and restored_frequency is not None
                    and abs(
                        round(float(restored_frequency) * 1_000_000) - original_hz
                    ) <= (0 if _icom_supported(radio) else 10)
                )
            except Exception:
                DEBUG_LOG.exception("Could not restore previous frequency port=%s", radio.port)
                restored = False
        if restored:
            DEBUG_LOG.info("Previous frequency restored frequency_mhz=%s", original_frequency)
            return _read_label(
                root, language, "l063",
                "Requested frequency was not accepted; previous frequency restored.",
            )
        return _read_label(
            root, language, "l067",
            "Frequency change failed; previous frequency may not have been restored.",
        )
    DEBUG_LOG.info("Frequency set verified requested_hz=%s actual_mhz=%s", hz, actual_frequency)
    return actual_frequency


def _radio_status(root: Path, radio: RadioConnection, language: str) -> str:
    if _icom_supported(radio):
        command_path = _radio_command_file(root, radio, "read", "w")
        if command_path is None:
            return _read_label(root, language, "l050", "Could not read frequency and mode from the radio.")
        return _icom_status(root, radio, language, command_path)
    if radio.protocol != "CAT" or radio.manufacturer_key not in {"yaesu", "kenwood"}:
        return _read_label(root, language, "l057", "No verified status profile is available for this radio.")
    if _ftx1(radio):
        frequency = _current_frequency(root, radio)
        mode = _current_mode(radio)
        side = _yaesu_vfo_side
        signal_response = _cat_exchange(radio, f"SM{side};")
        meter_match = re.search(rf"SM{side}(\d{{3}});", signal_response)
        if meter_match is None:
            # Some FTX-1 firmware answers SM1 with an SM0 prefix. RM0 returns
            # separately identified Main/Sub readings; do not guess the SM side.
            meters = re.search(r"RM0(\d{3})(\d{3});", _cat_exchange(radio, "RM0;"))
            if meters:
                raw = meters.group(1 + side)
                signal_response = f"SM{side}{raw};"
                meter_match = re.search(rf"SM{side}(\d{{3}});", signal_response)
        if meter_match:
            DEBUG_LOG.debug("FTX-1 S-meter side=%s raw=%s", "SUB" if side else "MAIN", meter_match.group(1))
        else:
            DEBUG_LOG.warning("FTX-1 S-meter response did not match expected side=%s response=%r", side, signal_response)
        signal = format_s_meter(int(meter_match.group(1)), radio.model_id) if meter_match else "S ?"
        return f"{signal} {frequency} {mode}" if frequency and mode else _read_label(
            root, language, "l050", "Could not read frequency and mode from the radio."
        )
    if radio.manufacturer_key == "kenwood":
        if radio.model_id == "020":
            frequency = _current_frequency(root, radio)
            mode = _current_mode(radio)
            match = re.search(r'SM0(\d{4});', _cat_exchange(radio, 'SM0;'))
            signal = f'S {int(match.group(1))}' if match else 'S ?'
            return f'{signal} {frequency} {mode}' if frequency and mode else _read_label(root, language, 'l050', '')
        command_path = _radio_command_file(root, radio, "read", "w")
        if command_path is None:
            return _read_label(root, language, "l050", "Could not read frequency and mode from the radio.")
        try:
            commands = [part.strip() for part in command_path.read_text(encoding="ascii").split(";") if part.strip()]
        except OSError:
            return _read_label(root, language, "l056", "Could not read the radio status command file.")
        responses = "".join(_cat_exchange(radio, command + ";") for command in commands)
        frequency_match = re.search(r"FA(\d{11});", responses)
        mode_match = re.search(r"MD([1-9]);", responses)
        meter_match = re.search(r"SM0(\d{4});", responses)
        frequency = _frequency_mhz(frequency_match.group(1)) if frequency_match else None
        mode = KENWOOD_MODE_LABELS.get(mode_match.group(1)) if mode_match else None
        # Kenwood reports the displayed S-meter bar dots (0000-0030), not a
        # calibrated raw strength scale; retain the reading without conversion.
        signal = f"S {int(meter_match.group(1))}" if meter_match else "S ?"
        if frequency and mode:
            return f"{signal} {frequency} {SHORT_MODE_LABELS.get(mode, mode.replace('-', ''))}"
        return _read_label(root, language, "l050", "Could not read frequency and mode from the radio.")
    command_path = _radio_command_file(root, radio, "read", "w")
    if command_path is None:
        return _read_label(root, language, "l050", "Could not read frequency and mode from the radio.")
    try:
        commands = [part.strip() for part in command_path.read_text(encoding="ascii").split(";") if part.strip()]
    except OSError:
        return _read_label(root, language, "l056", "Could not read the radio status command file.")
    responses = ""
    for command in commands:
        responses += _cat_exchange(radio, command + ";")
    frequency_match = re.search(r"FA(\d{5,11});", responses)
    mode_match = re.search(r"MD0([0-9A-F]);", responses)
    meter_match = re.search(r"SM0(\d{3});", responses)
    frequency = _frequency_mhz(frequency_match.group(1)) if frequency_match else None
    mode = None
    if mode_match:
        mode = MODE_LABELS.get(mode_match.group(1), "?")
    signal = (
        format_s_meter(int(meter_match.group(1)), radio.model_id)
        if meter_match else "S ?"
    )
    if frequency and mode:
        return f"{signal} {frequency} {SHORT_MODE_LABELS.get(mode, mode.replace('-', ''))}"
    return _read_label(root, language, "l050", "Could not read frequency and mode from the radio.")


def _dispatch(
    root: Path, radio: RadioConnection, language: str, command: str,
    argument: str | None, original_frequency: str | None = None,
) -> str | None:
    if command == "t":
        from modules import tuner_control
        return tuner_control.tune(sys.modules[__name__], root, radio, language)
    if command == "w":
        from modules import tone_status
        status = _radio_status(root, radio, language)
        tone = tone_status.report(sys.modules[__name__], root, radio, language)
        return f"{status}, {tone}" if tone else status
    if command == "e" and argument is not None:
        return _set_frequency(root, radio, language, argument, original_frequency)
    if command == "h":
        from modules import help_int

        return help_int.get_help(root, language)
    return _read_label(root, language, "l049", "Command not available yet.")


def connect_radio(ini_path: Path | None = None) -> RadioConnection | None:
    """Load the user's language and discover the selected radio."""
    root = project_root()
    ini_path = (ini_path or root / "yac.ini").expanduser().resolve()
    settings = _read_settings(ini_path)

    platform = detect_platform()
    saved_platform = settings.get("platform", "")
    if saved_platform.casefold() != platform.casefold():
        language = settings.get("lang", "").casefold()
        if language not in lang_sel.LANGUAGE_CODES:
            language = "en"
        if saved_platform:
            message = _read_label(
                root, language, "l029",
                "The saved platform did not match this computer. Correcting it to {platform}.",
            )
            print(message.format(platform=platform))
        _set_yac_value(ini_path, "platform", platform)

    settings = _read_settings(ini_path)
    saved_language = settings.get("lang", "")
    if saved_language and saved_language.casefold() not in lang_sel.LANGUAGE_CODES:
        print(_read_label(
            root, "en", "l030",
            "The saved language '{language}' is not supported. Please select a language.",
        ).format(language=saved_language))
    language = _ensure_language(root, ini_path, settings.get("lang", ""))
    if language is None:
        return None
    settings = _read_settings(ini_path)
    from modules.name_call_sel import MAX_CALL_LENGTH, collect_name

    saved_call = settings.get("call", "").strip()
    _show_welcome(root, language, saved_call)
    if not saved_call:
        collect_name(root, ini_path, language)
    elif len(saved_call) > MAX_CALL_LENGTH:
        message = _read_label(
            root, language, "l031",
            "The saved name/callsign exceeds 10 characters. Please review it and confirm a new value.",
        )
        print(message)
        collect_name(root, ini_path, language, initial=saved_call)
    print(_read_label(root, language, "l058", "Searching for a connected radio."))
    sys.stdout.flush()
    DEBUG_LOG.info("Starting configured-port probe and radio discovery")
    radios = find_radios(ini_path)
    DEBUG_LOG.info("Radio discovery returned %d radio(s)", len(radios))
    if not radios:
        from modules.dummy_radio import create_dummy_radio
        print(_read_label(root, language, "l009", "No radio found. Loading the FT-DX10 demo."))
        DEBUG_LOG.info("Loading in-memory FT-DX10 demo")
        return create_dummy_radio()
    return _choose_radio(radios, root, language)


def main(argv: list[str] | None = None) -> int:
    argument_parser = argparse.ArgumentParser(description="Yet Another Controller")
    argument_parser.add_argument(
        "--debug", action="store_true",
        help="write radio command diagnostics to logs/yac-debug.log",
    )
    args = argument_parser.parse_args(argv)
    root = project_root()
    startup_settings = _read_settings(root / "yac.ini")
    debug_enabled = args.debug or startup_settings.get("debug", "").casefold() in {
        "1", "true", "yes", "on",
    }
    try:
        _configure_debug(root, debug_enabled)
    except OSError as error:
        print(f"Could not enable YAC debug logging: {error}", file=sys.stderr)
        return 1
    DEBUG_LOG.info("Starting YAC")
    try:
        radio = connect_radio(root / "yac.ini")
    except (OSError, configparser.Error, RuntimeError) as error:
        print(f"YAC could not start: {error}", file=sys.stderr)
        return 1
    if radio is None:
        settings = _read_settings(root / "yac.ini")
        language = settings.get("lang", "en") or "en"
        print(_read_label(
            root, language, "l028", "YAC could not find a responding radio."
        ), file=sys.stderr)
        return 1

    settings = _read_settings(root / "yac.ini")
    language = settings.get("lang", "en") or "en"
    label = _read_label(root, language, "l107", "Demo mode: simulated FT-DX10. No radio is connected.") if radio.is_dummy else _read_label(root, language, "l008", "Radio Connected")
    if radio.is_dummy:
        print(label)
    DEBUG_LOG.info(
        "Radio ready model=%s id=%s protocol=%s port=%s baud=%s address=%s",
        radio.model_name, radio.model_id, radio.protocol, radio.port,
        radio.baudrate, radio.civ_address,
    )

    from modules import chat_int, lang_sel
    pending_key: str | None = None
    call = settings.get("call", "YAC")
    chat_int.show_prompt(call)
    if radio.is_dummy:
        chat_int.show_response(_read_label(root, language, "l055", "Simulated Mode"))
    else:
        chat_int.show_response(f"{label} {radio.model_name}")
    from modules.connection_watch import ConnectionWatch
    def announce_connection(event):
        key, fallback = (
            ("l109", "Radio connection lost. Waiting for the same radio to reconnect.")
            if event == "lost" else ("l110", "Radio connection restored.")
        )
        chat_int.show_response(_read_label(root, language, key, fallback))
    watch = ConnectionWatch(radio, lambda: _current_frequency(root, radio), announce_connection)
    from modules.decoder_control import DecoderManager
    decoders = DecoderManager(sys.modules[__name__], root, radio, language)
    def read_radio_key(idle_callback=None):
        if idle_callback is not None:
            def idle():
                decoders.tick()
                watch.tick()
                idle_callback()
            return lang_sel.read_key(idle_callback=idle)
        if radio.is_dummy:
            return lang_sel.read_key()
        def idle():
            decoders.tick()
            watch.tick()
        return lang_sel.read_key(idle_callback=idle)
    prompt_open = True
    where_details_next = False
    try:
        while True:
            if pending_key is not None:
                key, pending_key = pending_key, None
            else:
                try:
                    key = read_radio_key()
                except (RuntimeError, OSError) as error:
                    print(f"\n{error}", file=sys.stderr)
                    break
            if not key:
                continue
            key = key.casefold()
            if key != "w":
                where_details_next = False
            DEBUG_LOG.debug("Top-level key=%r", key)
            chat_int.show_request(call, key, prompt_open=prompt_open)
            prompt_open = False
            if key == "q":
                chat_int.show_goodbye(root, language, call)
                break
            if watch.lost:
                if key == "h":
                    chat_int.show_response(_dispatch(root, radio, language, key, None) or "")
                else:
                    announce_connection("lost")
                continue
            if key == "w":
                response = (split_control.report(sys.modules[__name__], root, radio, language)
                            if where_details_next else _dispatch(root, radio, language, key, None))
                where_details_next = not where_details_next
            elif key == "e":
                original_frequency = _current_frequency(root, radio)
                if original_frequency is None:
                    response = _read_label(
                        root, language, "l066",
                        "Could not read current frequency; change cancelled.",
                    )
                else:
                    chat_int.show_frequency_prompt(root, language)
                    try:
                        frequency = input().strip()
                    except (EOFError, KeyboardInterrupt):
                        print()
                        continue
                    response = _dispatch(
                        root, radio, language, key, frequency, original_frequency
                    )
            elif key == "m":
                modes = _available_modes(radio)
                current_mode = _current_mode_code(radio)
                if not modes or current_mode is None:
                    chat_int.show_response(
                        _read_label(root, language, "l089", "Mode change failed.")
                    )
                    response = None
                    continue
                mode_index = next(
                    (i for i, (code, _name) in enumerate(modes) if code == current_mode),
                    0,
                )
                mode_select_label = _read_label(root, language, "l088", "Mode Select")
                chat_int.show_response(
                    f"{mode_select_label} {_mode_name(radio, modes[mode_index][0])}"
                )
                response = None
                while True:
                    try:
                        mode_key = read_radio_key()
                    except (RuntimeError, OSError) as error:
                        print(f"\n{error}", file=sys.stderr)
                        break
                    if watch.lost:
                        pending_key = mode_key or "w"
                        break
                    mode_key = mode_key.casefold()
                    if not mode_key:
                        continue
                    if mode_key in {UP_KEY, DOWN_KEY}:
                        direction = 1 if mode_key == UP_KEY else -1
                        next_index = (mode_index + direction) % len(modes)
                        chat_int.show_request(call, mode_key)
                        if _set_mode(radio, modes[next_index][0]):
                            mode_index = next_index
                            mode_response = _mode_name(radio, modes[mode_index][0])
                        else:
                            mode_response = _read_label(
                                root, language, "l089", "Mode change failed."
                            )
                        chat_int.show_response(mode_response)
                        continue
                    if mode_key == "h":
                        from modules import help_int
                        chat_int.show_request(call, mode_key)
                        chat_int.show_response(help_int.get_help(root, language, "h003"))
                        continue
                    if mode_key == "q":
                        chat_int.show_back(root, language)
                        chat_int.show_request(call, mode_key)
                        break
                    DEBUG_LOG.debug(
                        "Leaving mode selection and queueing command key=%r", mode_key,
                    )
                    pending_key = mode_key
                    break
            elif key == "b":
                chat_int.show_response(
                    _read_label(root, language, "l090", "Band Select")
                )
                while True:
                    try:
                        band_key = read_radio_key()
                    except (RuntimeError, OSError) as error:
                        print(f"\n{error}", file=sys.stderr)
                        break
                    if watch.lost:
                        pending_key = band_key or "w"
                        break
                    band_key = band_key.casefold()
                    if not band_key:
                        continue
                    if band_key in {UP_KEY, DOWN_KEY}:
                        direction = 1 if band_key == UP_KEY else -1
                        DEBUG_LOG.debug("Band adjustment key=%r", band_key)
                        chat_int.show_request(call, band_key)
                        chat_int.show_response(_band_change(root, radio, language, direction))
                    elif band_key == "h":
                        from modules import help_int
                        chat_int.show_request(call, band_key)
                        chat_int.show_response(help_int.get_help(root, language, "h002"))
                    elif band_key == "q":
                        chat_int.show_back(root, language)
                        chat_int.show_request(call, band_key)
                        break
                    else:
                        DEBUG_LOG.debug("Leaving band adjustment and queueing command key=%r", band_key)
                        pending_key = band_key
                        break
                response = None
            elif key == "f":
                pending_key = filter_control.control(
                    sys.modules[__name__], root, radio, language,
                    call, read_radio_key, watch)
                response = None
            elif key in {"a", "r"}:
                pending_key = gain_control.control(
                    sys.modules[__name__], root, radio, language, key,
                    call, read_radio_key, watch)
                response = None
            elif key in {"p", "u", "v"}:
                response = (verify_settings.verify(sys.modules[__name__], root, radio, language)
                            if key == "v" else verify_settings.cycle(
                                sys.modules[__name__], root, radio, language,
                                "preamp" if key == "p" else "attenuator"))
            elif key == "s":
                response = _read_label(root, language, "l068", "Settings")
                chat_int.show_response(response)
                response = None
                while True:
                    try:
                        settings_key = read_radio_key()
                    except (RuntimeError, OSError) as error:
                        print(f"\n{error}", file=sys.stderr)
                        response = None
                        break
                    if watch.lost:
                        pending_key = settings_key or "w"
                        break
                    if not settings_key:
                        continue
                    settings_key = settings_key.casefold()
                    if settings_key == "s":
                        DEBUG_LOG.debug("Settings key=%r", settings_key)
                        chat_int.show_request(call, settings_key)
                        step_profile = _step_size_key(_current_mode(radio))
                        if step_profile is None:
                            response = _read_label(root, language, "l072", "NOT Understood.")
                            break
                        setting_key, mode_name = step_profile
                        chat_int.show_step_size_prompt(root, language, mode_name)
                        try:
                            entered_step = input().strip()
                        except (EOFError, KeyboardInterrupt):
                            print()
                            response = None
                            break
                        try:
                            step_hz = int(entered_step)
                        except ValueError:
                            step_hz = 0
                        if (
                            not entered_step.isascii()
                            or not entered_step.isdecimal()
                            or step_hz <= 0
                        ):
                            response = _read_label(
                                root, language, "l071",
                                "Enter a whole number of hertz greater than zero.",
                            )
                            break
                        try:
                            _set_yac_value(root / "yac.ini", setting_key, str(step_hz))
                        except OSError:
                            DEBUG_LOG.exception("Could not save %s to yac.ini", setting_key)
                            response = _read_label(
                                root, language, "l073", "Could not save the step size.",
                            )
                            break
                        settings[setting_key] = str(step_hz)
                        applied_template = _read_label(
                            root, language, "l070", "Step size {value} Hz applied.",
                        )
                        response = applied_template.format(value=step_hz)
                        chat_int.show_response(response)
                        response = None
                        continue
                    if settings_key == "e":
                        speech_processor.control(sys.modules[__name__], root, radio, language, read_radio_key, watch)
                        continue
                    if settings_key == "a":
                        chat_int.show_response(agc_control.cycle(sys.modules[__name__], root, radio, language))
                        continue
                    if settings_key == "h":
                        from modules import help_int
                        chat_int.show_response(help_int.get_help(root, language, "h009"))
                        continue
                    if settings_key == "m":
                        mic_gain.control(sys.modules[__name__], root, radio, language, read_radio_key, watch)
                        continue
                    if settings_key == "p":
                        chat_int.show_request(call, settings_key)
                        power_control.edit(sys.modules[__name__], root, radio, language)
                        continue
                    if settings_key == "t":
                        chat_int.show_request(call, settings_key)
                        chat_int.show_response(verify_settings.cycle(
                            sys.modules[__name__], root, radio, language, "tuner"))
                        continue
                    if settings_key == "v":
                        global _yaesu_vfo_side
                        if radio.protocol == "CAT" and radio.model_id == "020":
                            chat_int.show_response(ts480_control.select_vfo(
                                sys.modules[__name__], root, radio, language))
                            continue
                        if _icom_supported(radio):
                            chat_int.show_request(call, settings_key)
                            chat_int.show_response(_icom_select_vfo(root, radio, language))
                            continue
                        if not _ftx1(radio):
                            response = _read_label(root, language, "l072", "NOT Understood.")
                            break
                        _yaesu_vfo_side = 1 - _yaesu_vfo_side
                        side_name = "Sub" if _yaesu_vfo_side else "Main"
                        frequency = _current_frequency(root, radio)
                        mode = _current_mode(radio)
                        chat_int.show_request(call, settings_key)
                        response = (
                            f"{side_name} {frequency} {mode}"
                            if frequency and mode
                            else _read_label(root, language, "l050", "Could not read frequency and mode from the radio.")
                        )
                        chat_int.show_response(response)
                        response = None
                        continue
                    if settings_key == "q":
                        chat_int.show_back(root, language)
                        chat_int.show_request(call, settings_key)
                        response = None
                        break
                    DEBUG_LOG.debug("Leaving Settings and queueing command key=%r", settings_key)
                    pending_key = settings_key
                    response = None
                    break
            elif key == "d":
                decoders.control(read_radio_key)
                response = None
            elif key == "x":
                pending_key = antenna_control.control(
                    sys.modules[__name__], root, radio, language, read_radio_key, watch)
                response = None
            elif key == "l":
                split_control.control(sys.modules[__name__], root, radio, language)
                response = None
            elif key == "i":
                response = None
                try:
                    _tone_control(root, radio, language, call)
                except (RuntimeError, OSError) as error:
                    print(f"\n{error}", file=sys.stderr)
                except (EOFError, KeyboardInterrupt):
                    print()
            elif key == "o":
                offset_selection = 0  # Receive; cycles Receive, Transmit, Clear.
                if not _zero_offsets(radio):
                    chat_int.show_response(
                        _read_label(root, language, "l085", "Offset change failed.")
                    )
                    response = None
                    continue
                response = _offset_label(root, language, offset_selection)
                chat_int.show_response(response)
                response = None
                while True:
                    try:
                        offset_key = read_radio_key()
                    except (RuntimeError, OSError) as error:
                        print(f"\n{error}", file=sys.stderr)
                        break
                    if watch.lost:
                        pending_key = offset_key or "w"
                        break
                    if not offset_key:
                        continue
                    offset_key = offset_key.casefold()
                    if offset_key == "o":
                        offset_selection = (offset_selection + 1) % 3
                        chat_int.show_request(call, offset_key)
                        chat_int.show_response(
                            _offset_label(root, language, offset_selection)
                        )
                        continue
                    if offset_key in {UP_KEY, DOWN_KEY}:
                        chat_int.show_request(call, offset_key)
                        try:
                            offset_response = _offset_action(
                                root, radio, language, offset_selection,
                                1 if offset_key == UP_KEY else -1,
                            )
                        except Exception:
                            DEBUG_LOG.exception(
                                "Offset command failed model=%s side=%s selection=%s",
                                radio.model_id, _yaesu_vfo_side, offset_selection,
                            )
                            offset_response = _read_label(
                                root, language, "l085", "Offset change failed.",
                            )
                        chat_int.show_response(offset_response)
                        continue
                    if offset_key == "q":
                        chat_int.show_back(root, language)
                        chat_int.show_request(call, offset_key)
                        break
                    DEBUG_LOG.debug(
                        "Leaving offset control and queueing command key=%r",
                        offset_key,
                    )
                    pending_key = offset_key
                    break
            elif key in {UP_KEY, DOWN_KEY}:
                response = _step_frequency(
                    root, radio, language, settings,
                    1 if key == UP_KEY else -1,
                )
            elif key == "z":
                response = _round_frequency_to_khz(root, radio, language)
            else:
                response = _dispatch(root, radio, language, key, None)
            chat_int.show_response(response or "")
    finally:
        decoders.close()
        radio.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
