"""Discover transceivers on Windows, Linux, and macOS serial ports.

Discovery order:
1. Enumerate ports through PySerial and rank them using USB/device metadata.
2. Try CI-V read-frequency/read-mode queries on ports that look like Icom
   interfaces or use a Silicon Labs USB serial bridge. A matching port pair
   raises confidence that the bridge belongs to a radio.
3. Try the read-only ASCII CAT command ``FA;`` at common radio baud rates.
4. If frequency responds, ask for the read-only CAT model ID with ``ID;``.

The module never sends a command that sets frequency, mode, PTT, or any other
radio setting. Opening an unfamiliar COM port can still change RTS/DTR briefly
on some Windows drivers. RTS and DTR are prepared as deasserted before opening;
radios/interfaces configured to key PTT from these lines should have that
feature disabled before discovery.

``find_radio()`` returns an open RadioConnection for yac.py to reuse. The
standalone command also saves successful connection details to yac.ini, then
closes the port when it exits.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path


DEBUG_LOG = logging.getLogger("yac")
from typing import Any


# Start with the fastest common CAT rates. Modern radios such as the IC-705
# support high rates, and 4800 baud needlessly slows discovery when it is tried first.
BAUD_RATES = (115200, 57600, 38400, 19200, 9600, 4800, 2400, 1200, 300)
CONTROLLER_ADDRESS = 0xE0

# Common factory CI-V addresses. The local manuals include A4 for the IC-705
# and A2 for the IC-9700; other entries provide sensible first guesses when
# Windows identifies an Icom USB interface. A user-supplied civ_address is
# always tried first.
CIV_ADDRESSES = (0xA4, 0x7A, 0xA2, 0x94, 0xB6, 0x98, 0x88, 0x70, 0x5C, 0x58)
CAT_MODELS = {
    "0761": "Yaesu FTDX10",
    "0840": "Yaesu FTX-1",
    "021": "Kenwood TS-590S",
    "023": "Kenwood TS-590SG",
    "019": "Kenwood TS-2000",
    "024": "Kenwood TS-890",
}
CI_V_MODELS = {
    "A4": "IC-705",
    "94": "IC-7300",
    "B6": "IC-7300MK2",
    "A2": "IC-9700",
    "7A": "IC-7600",
    "98": "IC-7610",
    "88": "IC-7100",
}
YAESU_CAT_IDS = frozenset({"0761", "0800", "0840"})
KENWOOD_CAT_IDS = frozenset({"021", "023", "019", "024", "020"})


def project_root() -> Path:
    module_directory = Path(__file__).resolve().parent
    if module_directory.name.casefold() == "modules":
        return module_directory.parent
    return module_directory


def _config_values(ini_path: Path) -> dict[str, str]:
    """Read key/value lines inside [yac], tolerating unrelated legacy lines."""
    if not ini_path.exists():
        return {}
    try:
        contents = ini_path.read_text(encoding="utf-8-sig")
    except OSError:
        return {}

    in_yac = False
    values: dict[str, str] = {}
    lines = contents.splitlines()
    for index, line in enumerate(lines):
        section = re.match(r"^\s*\[([^\]]+)\]", line)
        if section:
            in_yac = section.group(1).strip().casefold() == "yac"
            continue
        if not in_yac or line.lstrip().startswith((";", "#")):
            continue
        match = re.match(r"^\s*([^=:#]+?)\s*=\s*(.*?)\s*$", line)
        if match:
            key = match.group(1).strip().casefold()
            value = match.group(2).strip()
            # Read legacy files where a value was accidentally placed on the
            # line below its key. New writes use standard one-line INI values.
            if not value and index + 1 < len(lines):
                next_line = lines[index + 1].strip()
                if next_line and "=" not in next_line and not next_line.startswith(("[", ";", "#")):
                    value = next_line
            values[key] = value
    return values


def _radio_profiles(ini_path: Path) -> list[dict[str, str]]:
    """Read [radio:...] sections without requiring a platform-specific INI library."""
    if not ini_path.exists():
        return []
    try:
        lines = ini_path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return []
    profiles: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for line in lines:
        section = re.match(r"^[ \t]*\[([^\]]+)\]", line)
        if section:
            name = section.group(1).strip()
            current = {"_section": name} if name.casefold().startswith("radio:") else None
            if current is not None:
                profiles.append(current)
            continue
        if current is None or line.lstrip().startswith((";", "#")):
            continue
        match = re.match(r"^[ \t]*([^=:#]+?)[ \t]*=[ \t]*(.*?)[ \t]*$", line)
        if match:
            current[match.group(1).strip().casefold()] = match.group(2).strip()
    return profiles


def _platform_name() -> str:
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("linux"):
        return "linux"
    return "other"


def _profile_port_hint(profile: dict[str, str]) -> str:
    platform = _platform_name()
    return profile.get(f"port_hint_{platform}", "") or profile.get("port_hint", "")


def _usb_identity(port: Any) -> str:
    """Return a persistent USB identity when the adapter exposes a serial number."""
    vid, pid = getattr(port, "vid", None), getattr(port, "pid", None)
    serial_number = getattr(port, "serial_number", None)
    if vid is None or not serial_number:
        return ""
    return f"{vid:04X}:{(pid or 0):04X}:{serial_number.strip()}"


def _port_details(port: Any) -> dict[str, str | None]:
    """Capture the serial and USB properties needed for future diagnostics."""
    details: dict[str, str | None] = {}
    for name in ("device", "description", "hwid", "manufacturer", "product", "interface",
                 "serial_number", "location"):
        value = getattr(port, name, None)
        details[name] = str(value) if value not in (None, "") else None
    for name in ("vid", "pid"):
        value = getattr(port, name, None)
        details[name] = f"{value:04X}" if value is not None else None
    return details


def _silicon_labs_evidence(port: Any) -> list[str]:
    """Report visible USB clues, without claiming a driver is installed."""
    evidence = []
    if getattr(port, "vid", None) == 0x10C4:
        evidence.append("USB vendor ID 10C4")
    for name in ("description", "manufacturer", "product", "interface", "hwid"):
        value = str(getattr(port, name, "") or "")
        if "cp210" in value.casefold() or "silicon lab" in value.casefold():
            evidence.append(f"{name}: {value}")
    return evidence


def _diagnostic_port_details(port: Any) -> dict:
    details = _port_details(port)
    evidence = _silicon_labs_evidence(port)
    details["silicon_labs_metadata_seen"] = bool(evidence)
    details["silicon_labs_evidence"] = evidence
    return details


def _log_port_diagnostics(ports: list[Any]) -> None:
    if not DEBUG_LOG.isEnabledFor(logging.INFO):
        return
    details = [_diagnostic_port_details(port) for port in ports]
    seen = any(port["silicon_labs_metadata_seen"] for port in details)
    DEBUG_LOG.info("Serial-port metadata: %s", json.dumps(details, ensure_ascii=True))
    DEBUG_LOG.info("silicon_labs_metadata_seen=%s (visible device metadata; not an installed-driver check)",
                   str(seen).lower())
    if not seen:
        DEBUG_LOG.info(
            "No Silicon Labs identifier was found in the visible serial-port metadata. "
            "Devices may be identified differently; this does not mean the driver is missing. "
            "If using the radio's direct USB connection and discovery fails, it may help to "
            "check the manufacturer's USB driver and the device name/status in Device Manager. "
            "External CI-V interfaces may use a different manufacturer's driver."
        )


def serial_port_diagnostics() -> list[dict]:
    """Return current PySerial port/USB metadata for an opt-in debug report."""
    from serial.tools import list_ports

    return [_diagnostic_port_details(port) for port in list_ports.comports()]


def _port_text(port: Any) -> str:
    fields = (
        getattr(port, "device", ""), getattr(port, "description", ""),
        getattr(port, "hwid", ""), getattr(port, "manufacturer", ""),
        getattr(port, "product", ""), getattr(port, "interface", ""),
    )
    return " ".join(str(value or "") for value in fields).casefold()


def _usb_pair_keys(port: Any) -> tuple[str, ...]:
    vid = getattr(port, "vid", None)
    if vid is None:
        return ()
    pid = getattr(port, "pid", None)
    serial_number = getattr(port, "serial_number", None)
    location = getattr(port, "location", None)
    if serial_number:
        return (f"{vid:04x}:{(pid or 0):04x}:ser:{serial_number.casefold()}",)
    if location:
        parent_location = str(location).split(":", 1)[0]
        return (f"{vid:04x}:{(pid or 0):04x}:loc:{parent_location.casefold()}",)
    return ()


def _rank_ports(ports: list[Any], preferred_ports: tuple[str, ...] = ()) -> list[Any]:
    pair_counts: dict[str, int] = {}
    for port in ports:
        for key in _usb_pair_keys(port):
            pair_counts[key] = pair_counts.get(key, 0) + 1

    def score(port: Any) -> tuple[int, str]:
        text = _port_text(port)
        device = str(getattr(port, "device", ""))
        total = 0
        if any(device.casefold() == hint.casefold() for hint in preferred_ports if hint):
            total += 1000
        if any(word in text for word in ("icom", "ci-v", "transceiver", "radio")):
            total += 100
        if "enhanced com" in text or "cat-1" in text:
            total += 70
        if "standard com" in text or "cat-2" in text:
            total += 40
        if getattr(port, "vid", None) == 0x10C4:  # Silicon Labs CP210x
            total += 30
        if any(pair_counts.get(key, 0) > 1 for key in _usb_pair_keys(port)):
            total += 25
        if getattr(port, "vid", None) is not None:
            total += 5
        if sys.platform.startswith("linux"):
            if re.match(r"^/dev/tty(?:USB|ACM)\d+$", device):
                total += 50
            elif device.startswith("/dev/ttyS"):
                total -= 20
        elif sys.platform == "darwin":
            if device.startswith("/dev/cu."):
                total += 50
            elif device.startswith("/dev/tty."):
                total -= 10
        return (-total, device)

    return sorted(ports, key=score)


def _is_icom_candidate(port: Any, paired_silabs: bool) -> bool:
    text = _port_text(port)
    if any(word in text for word in ("icom", "ci-v", "ic-705", "ic-7300", "ic-9700", "ic-7600")):
        return True
    # A Silicon Labs bridge is a useful radio clue; a second matching COM port
    # raises its ranking, but a single bridge can still be the radio CAT port.
    return bool(_silicon_labs_evidence(port)) or paired_silabs


def _is_paired_silabs(port: Any, ports: list[Any]) -> bool:
    is_silabs = bool(_silicon_labs_evidence(port))
    if not is_silabs:
        return False
    keys = set(_usb_pair_keys(port))
    return any(
        other is not port and keys.intersection(_usb_pair_keys(other))
        for other in ports
    )


def _open_serial(port_name: str, baudrate: int, serial_module: Any) -> Any:
    connection = serial_module.Serial(
        port=None,
        baudrate=baudrate,
        bytesize=serial_module.EIGHTBITS,
        parity=serial_module.PARITY_NONE,
        stopbits=serial_module.STOPBITS_ONE,
        timeout=0.15,
        write_timeout=0.35,
        xonxoff=False,
        rtscts=False,
        dsrdtr=False,
    )
    # Set control-line states while closed, before assigning/opening the COM
    # handle. PySerial exposes these as properties, not constructor keywords.
    connection.rts = False
    connection.dtr = False
    connection.port = port_name
    connection.open()
    # Apply the preferred idle values again after open in case the Windows
    # driver initialized either output line while creating the handle.
    connection.rts = False
    connection.dtr = False
    time.sleep(0.08)
    return connection


def _exchange(connection: Any, packet: bytes, terminator: bytes, limit: int = 96) -> bytes:
    connection.reset_input_buffer()
    connection.write(packet)
    connection.flush()
    response = bytearray()
    deadline = time.monotonic() + float(connection.timeout or 0.15)
    quiet_deadline: float | None = None
    while time.monotonic() < deadline and len(response) < limit:
        waiting = connection.in_waiting
        chunk = connection.read(min(waiting, limit - len(response)) if waiting else 1)
        if chunk:
            response.extend(chunk)
            if terminator in response:
                # Some USB bridges echo the outgoing frame before the radio's
                # answer. Briefly collect trailing frames before validating.
                quiet_deadline = time.monotonic() + 0.035
        elif quiet_deadline is not None and time.monotonic() >= quiet_deadline:
            break
    return bytes(response)


def _valid_cat_frequency(response: bytes) -> str | None:
    match = re.search(rb"(?:^|[^A-Z])FA([0-9]{5,11});", response.upper())
    if not match:
        return None
    digits = match.group(1).decode("ascii")
    frequency_hz = int(digits)
    if not 100_000 <= frequency_hz <= 1_000_000_000:
        return None
    return digits


def _cat_model_id(connection: Any) -> str:
    try:
        response = _exchange(connection, b"ID;", b";", 48).upper()
    except Exception:
        return ""
    match = re.search(rb"(?:^|[^A-Z])ID([0-9]{3,4});", response)
    return match.group(1).decode("ascii") if match else ""


def _yaesu_main_mode(connection: Any, model_id: str) -> str:
    """Read a Yaesu main-band mode; MD0; selects MAIN for this read."""
    if model_id not in {"0761", "0840"}:
        return ""
    try:
        response = _exchange(connection, b"MD0;", b";", 48).upper()
    except Exception:
        return ""
    match = re.search(rb"(?:^|[^A-Z])MD0([0-9A-F]);", response)
    return match.group(1).decode("ascii") if match else ""


def _cat_model_name(model_id: str, port_info: Any) -> str:
    text = _port_text(port_info)
    if model_id == "020":
        if "qmx" in text or "qrp labs" in text:
            if any(name in text for name in ('qmx+', 'qmx plus', 'qmxplus')):
                return "QRP Labs QMX Plus (Kenwood-compatible CAT ID 020)"
            return "QRP Labs QMX (Kenwood-compatible CAT ID 020)"
        return "CAT radio ID 020 (Kenwood TS-480/QMX-compatible ID)"
    if model_id in CAT_MODELS:
        return CAT_MODELS[model_id]
    return f"CAT radio (ID {model_id})" if model_id else "CAT-compatible radio"


def _probe_cat(connection: Any, baud_hints: list[int]) -> tuple[int, str, str] | None:
    for baudrate in baud_hints:
        try:
            connection.baudrate = baudrate
            connection.timeout = 0.16
            response = _exchange(connection, b"FA;", b";", 48)
            frequency = _valid_cat_frequency(response)
            if frequency is None:
                continue
            model_id = _cat_model_id(connection)
            return baudrate, model_id, frequency
        except Exception:
            continue
    return None


def _civ_response_data(response: bytes, address: int, command: int) -> bytes | None:
    marker = bytes((0xFE, 0xFE, CONTROLLER_ADDRESS, address, command))
    start = response.find(marker)
    if start < 0:
        return None
    end = response.find(b"\xFD", start + len(marker))
    if end < 0:
        return None
    return response[start + len(marker):end]


def _valid_civ_frequency(data: bytes | None) -> bool:
    if data is None or len(data) != 5:
        return False
    nonzero = False
    for value in data:
        low, high = value & 0x0F, (value >> 4) & 0x0F
        if low > 9 or high > 9:
            return False
        nonzero = nonzero or low != 0 or high != 0
    return nonzero


def _civ_transceiver_id(connection: Any, address: int) -> str:
    """Read Icom's CI-V transceiver ID (command 19 00), when supported."""
    try:
        request = bytes((0xFE, 0xFE, address, CONTROLLER_ADDRESS, 0x19, 0x00, 0xFD))
        response = _exchange(connection, request, b"\xFD", 32)
        data = _civ_response_data(response, address, 0x19)
        if data and data[0] == 0x00 and len(data) >= 2:
            return f"{data[1]:02X}"
    except Exception:
        pass
    return ""


def _probe_civ(
    connection: Any,
    baud_hints: list[int],
    address_hints: list[int],
) -> tuple[int, int, str, str] | None:
    for baudrate in baud_hints:
        try:
            connection.baudrate = baudrate
            connection.timeout = 0.12
        except Exception:
            continue
        for address in address_hints:
            try:
                request = bytes((0xFE, 0xFE, address, CONTROLLER_ADDRESS, 0x03, 0xFD))
                response = _exchange(connection, request, b"\xFD", 32)
                frequency_data = _civ_response_data(response, address, 0x03)
                if not _valid_civ_frequency(frequency_data):
                    continue

                mode_request = bytes((0xFE, 0xFE, address, CONTROLLER_ADDRESS, 0x04, 0xFD))
                mode_response = _exchange(connection, mode_request, b"\xFD", 32)
                mode_data = _civ_response_data(mode_response, address, 0x04)
                if mode_data is None or not mode_data or mode_data[0] > 0x20:
                    continue
                model_id = _civ_transceiver_id(connection, address)
                return baudrate, address, "", model_id
            except Exception:
                continue
    return None


@dataclass
class RadioConnection:
    """An identified serial connection, left open for yac.py to use."""

    serial: Any
    port: str
    baudrate: int
    protocol: str
    model_id: str
    model_name: str
    frequency_digits: str = ""
    civ_address: int | None = None
    mode_code: str = ""
    usb_identity: str = ""
    port_details: dict[str, str | None] = field(default_factory=dict)
    is_dummy: bool = False

    @property
    def manufacturer_key(self) -> str:
        """Return the command-catalog manufacturer namespace, when known."""
        if self.protocol == "CI-V":
            return "icom"
        if self.protocol == "CAT":
            if self.model_id in YAESU_CAT_IDS:
                return "yaesu"
            if self.model_id in KENWOOD_CAT_IDS:
                return "kenwood"
        return "unknown"

    @property
    def protocol_key(self) -> str:
        return "CI-V" if self.protocol == "CI-V" else "CAT"

    @property
    def radio_id_path(self) -> str:
        """Return the model-specific command directory in the catalog tree."""
        if self.protocol == "CI-V":
            model_key = self.model_id.casefold().replace(" ", "-")
            return f"rad_cmds/icom/CI-V/models/{model_key}"
        protocol = "CAT" if self.protocol == "CAT" else self.protocol
        return (
            f"rad_cmds/{self.manufacturer_key}/{protocol}/models/"
            f"{self.model_id or 'unknown'}"
        )

    @property
    def common_command_path(self) -> str:
        """Return this manufacturer's shared-default command directory."""
        return f"rad_cmds/{self.manufacturer_key}/{self.protocol_key}/common"

    def close(self) -> None:
        self.serial.close()


def _probe_saved_profiles(
    profiles: list[dict[str, str]], ports: list[Any], serial_module: Any,
) -> list[RadioConnection]:
    """Connect to radios already recorded in the INI before broad discovery."""
    available_by_name = {
        str(getattr(port, "device", "") or "").casefold(): port for port in ports
    }
    available_by_usb = {
        _usb_identity(port): port for port in ports if _usb_identity(port)
    }
    found: list[RadioConnection] = []
    attempted: set[tuple[str, str, str, str]] = set()

    for profile in profiles:
        port_name = _profile_port_hint(profile)
        try:
            baudrate = int(profile.get("baud_rate", ""))
        except ValueError:
            continue
        protocol = profile.get("protocol", "").upper()
        model_id = profile.get("model_id", "").strip()
        usb_identity = profile.get("usb_identity", "").strip()
        port_info = available_by_name.get(port_name.casefold()) if port_name else None
        if port_info is None and usb_identity:
            port_info = available_by_usb.get(usb_identity)
        if port_info is None or baudrate <= 0 or protocol not in {"CAT", "CI-V"}:
            continue
        actual_port = str(getattr(port_info, "device", "") or "")
        attempt_key = (actual_port.casefold(), str(baudrate), protocol, model_id.casefold())
        if attempt_key in attempted:
            continue
        attempted.add(attempt_key)

        try:
            connection = _open_serial(actual_port, baudrate, serial_module)
        except Exception as error:
            DEBUG_LOG.warning(
                "Could not open saved radio port=%s baud=%s protocol=%s: %s",
                actual_port, baudrate, protocol, error,
            )
            continue

        try:
            if protocol == "CAT":
                # Query ID at the saved rate before asking for other state.
                actual_model_id = _cat_model_id(connection)
                if not actual_model_id or actual_model_id.casefold() != model_id.casefold():
                    connection.close()
                    continue
                response = _exchange(connection, b"FA;", b";", 48)
                frequency = _valid_cat_frequency(response)
                if frequency is None:
                    connection.close()
                    continue
                mode_code = _yaesu_main_mode(connection, actual_model_id)
                found.append(RadioConnection(
                    serial=connection, port=actual_port, baudrate=baudrate,
                    protocol="CAT", model_id=actual_model_id,
                    model_name=_cat_model_name(actual_model_id, port_info),
                    frequency_digits=frequency, mode_code=mode_code,
                    usb_identity=_usb_identity(port_info),
                    port_details=_port_details(port_info),
                ))
                continue

            try:
                address = int(profile.get("civ_address", ""), 0)
            except ValueError:
                try:
                    address = int(profile.get("civ_address", ""), 16)
                except ValueError:
                    connection.close()
                    continue
            actual_id = _civ_transceiver_id(connection, address)
            detected_model = CI_V_MODELS.get(actual_id, "")
            identified_model = detected_model or actual_id
            address_model = f"CI-V_{address:02X}"
            if (
                not actual_id
                or (identified_model.casefold() != model_id.casefold()
                    and actual_id.casefold() != model_id.casefold()
                    and address_model.casefold() != model_id.casefold())
            ):
                connection.close()
                continue
            frequency_response = _exchange(
                connection, bytes((0xFE, 0xFE, address, CONTROLLER_ADDRESS, 0x03, 0xFD)),
                b"\xFD", 32,
            )
            frequency_data = _civ_response_data(frequency_response, address, 0x03)
            if not _valid_civ_frequency(frequency_data):
                connection.close()
                continue
            mode_response = _exchange(
                connection, bytes((0xFE, 0xFE, address, CONTROLLER_ADDRESS, 0x04, 0xFD)),
                b"\xFD", 32,
            )
            mode_data = _civ_response_data(mode_response, address, 0x04)
            if not mode_data or mode_data[0] > 0x20:
                connection.close()
                continue
            found.append(RadioConnection(
                serial=connection, port=actual_port, baudrate=baudrate,
                protocol="CI-V", model_id=detected_model or model_id,
                model_name=detected_model or profile.get("model", "CI-V radio"),
                civ_address=address, usb_identity=_usb_identity(port_info),
                port_details=_port_details(port_info),
            ))
        except Exception:
            DEBUG_LOG.exception(
                "Saved radio probe failed port=%s baud=%s protocol=%s",
                actual_port, baudrate, protocol,
            )
            try:
                connection.close()
            except Exception:
                pass

    return found


def _baud_order(saved_baud: str, explicit_baud: int | None) -> list[int]:
    first: list[int] = []
    if explicit_baud:
        first.append(explicit_baud)
    # A saved rate is a hint, not a reason to skip the requested fast-first
    # scan. In particular, a profile created from a Standard COM port must not
    # make that slower interface/rate win over an Enhanced COM port.
    first.extend(BAUD_RATES)
    if saved_baud:
        try:
            saved = int(saved_baud)
            if saved not in first:
                first.append(saved)
        except ValueError:
            pass
    return list(dict.fromkeys(first))


def _same_radio_connection(left: RadioConnection, right: RadioConnection) -> bool:
    """Identify duplicate virtual ports belonging to one USB radio interface."""
    return bool(
        left.usb_identity
        and left.usb_identity == right.usb_identity
        and left.protocol.casefold() == right.protocol.casefold()
        and left.model_id.casefold() == right.model_id.casefold()
    )


def _connection_port_priority(radio: RadioConnection) -> tuple[int, int]:
    """Prefer the fastest responding rate, then Enhanced COM/CAT-1 on ties."""
    details = radio.port_details
    description = " ".join(
        str(details.get(key) or "") for key in ("description", "interface", "product")
    ).casefold()
    if "enhanced com" in description or "cat-1" in description:
        port_rank = 2
    elif "standard com" in description or "cat-2" in description:
        port_rank = 1
    else:
        port_rank = 0
    return radio.baudrate, port_rank


def _record_radio(found_radios: list[RadioConnection], found: RadioConnection) -> None:
    """Keep one preferred connection when a radio exposes paired COM ports."""
    for index, existing in enumerate(found_radios):
        if not _same_radio_connection(existing, found):
            continue
        if _connection_port_priority(found) > _connection_port_priority(existing):
            existing.close()
            found_radios[index] = found
        else:
            found.close()
        return
    found_radios.append(found)


def _address_order(saved_address: str, explicit_address: int | None) -> list[int]:
    preferred = explicit_address
    if preferred is None and saved_address:
        try:
            preferred = int(saved_address, 0)
        except ValueError:
            try:
                preferred = int(saved_address, 16)
            except ValueError:
                preferred = None
    addresses = ([preferred] if preferred is not None and 0 <= preferred <= 0xEF else [])
    return list(dict.fromkeys(addresses + list(CIV_ADDRESSES)))


def find_radios(
    ini_path: Path | None = None,
    *,
    port_hint: str = "",
    baud_hint: int | None = None,
    civ_address: int | None = None,
    save_to_ini: bool = True,
) -> list[RadioConnection]:
    """Find all responding radios and return their open serial connections.

    `port_hint`, `baud_hint`, and `civ_address` can be supplied by yac.ini or
    by a caller. Successful settings are saved using project-relative paths.
    The caller owns and must close every returned serial connection.
    """
    ini_path = (ini_path or project_root() / "yac.ini").expanduser().resolve()
    profiles = _radio_profiles(ini_path)
    found_radios: list[RadioConnection] = []
    preferred_ports = tuple(
        hint for hint in (port_hint, *(_profile_port_hint(profile) for profile in profiles)) if hint
    )
    try:
        import serial
        from serial.tools import list_ports
    except ImportError as error:
        print(f"Radio discovery needs PySerial: {error}", file=sys.stderr)
        return []

    try:
        ports = list(list_ports.comports())
    except Exception as error:
        DEBUG_LOG.exception("Could not enumerate serial ports")
        print(f"Could not enumerate serial ports: {error}", file=sys.stderr)
        return []
    DEBUG_LOG.info("Enumerated serial ports: %s", ", ".join(
        str(getattr(port, "device", "") or "?") for port in ports
    ))
    _log_port_diagnostics(ports)
    ports = _rank_ports(ports, preferred_ports)

    # Previously discovered radios get one direct attempt at their saved port
    # and baud rate. Only fall back to the exhaustive multi-rate scan if none
    # of the configured radios answers with its expected model ID.
    saved_radios = _probe_saved_profiles(profiles, ports, serial)
    if saved_radios:
        for radio in saved_radios:
            _save_connection(ini_path, radio, None)
        return saved_radios

    for port_info in ports:
        port_name = str(getattr(port_info, "device", "") or "")
        if not port_name:
            continue
        usb_identity = _usb_identity(port_info)
        port_profiles = [
            profile for profile in profiles
            if (
                _profile_port_hint(profile).casefold() == port_name.casefold()
                or (usb_identity and profile.get("usb_identity", "") == usb_identity)
            )
        ]
        saved_baud = next(
            (profile.get("baud_rate", "") for profile in port_profiles if profile.get("baud_rate")),
            "",
        )
        baudrates = _baud_order(saved_baud, baud_hint)
        saved_address = next(
            (profile.get("civ_address", "") for profile in port_profiles if profile.get("civ_address")),
            "",
        )
        address_hints = _address_order(saved_address, civ_address)
        civ_was_requested = civ_address is not None or any(
            profile.get("protocol", "").casefold() == "ci-v" for profile in port_profiles
        )
        known_cat_profile = any(
            profile.get("protocol", "").casefold() == "cat" for profile in port_profiles
        )
        try:
            connection = _open_serial(port_name, baudrates[0], serial)
        except Exception as error:
            DEBUG_LOG.warning(
                "Could not open discovered radio port=%s baud=%s: %s",
                port_name, baudrates[0], error,
            )
            continue

        paired_silabs = _is_paired_silabs(port_info, ports)
        try:
            if civ_was_requested or (
                not known_cat_profile and _is_icom_candidate(port_info, paired_silabs)
            ):
                civ_result = _probe_civ(connection, baudrates, address_hints)
                if civ_result:
                    baudrate, address, frequency, transceiver_id = civ_result
                    description = _port_text(port_info)
                    explicit_model = next(
                        (
                            model for model in ("IC-7300MK2", "IC-705", "IC-7300", "IC-9700", "IC-7600", "IC-7610", "IC-7100")
                            if model.casefold() in description
                        ),
                        "",
                    )
                    explicit_model = CI_V_MODELS.get(transceiver_id, "") or explicit_model
                    if explicit_model:
                        model_name = explicit_model
                        model_id = explicit_model
                    else:
                        maker = "Icom" if "icom" in description else "CI-V"
                        model_name = f"{maker} radio at address {address:02X}"
                        model_id = f"CI-V_{address:02X}"
                    connection.baudrate = baudrate
                    found = RadioConnection(
                        serial=connection, port=port_name, baudrate=baudrate,
                        protocol="CI-V", model_id=model_id, model_name=model_name,
                        frequency_digits=frequency, civ_address=address,
                        usb_identity=_usb_identity(port_info),
                        port_details=_port_details(port_info),
                    )
                    _record_radio(found_radios, found)
                    continue

            cat_result = _probe_cat(connection, baudrates)
            if cat_result:
                baudrate, model_id, frequency = cat_result
                model_name = _cat_model_name(model_id, port_info)
                mode_code = _yaesu_main_mode(connection, model_id)
                connection.baudrate = baudrate
                found = RadioConnection(
                    serial=connection, port=port_name, baudrate=baudrate,
                    protocol="CAT", model_id=model_id, model_name=model_name,
                    frequency_digits=frequency, mode_code=mode_code,
                    usb_identity=_usb_identity(port_info),
                    port_details=_port_details(port_info),
                )
                _record_radio(found_radios, found)
                continue
        except Exception:
            DEBUG_LOG.exception("Radio probe failed port=%s", port_name)
        try:
            connection.close()
        except Exception:
            pass
    if save_to_ini:
        for found in found_radios:
            _save_connection(ini_path, found, None)
    return found_radios


def find_radio(
    ini_path: Path | None = None,
    *,
    port_hint: str = "",
    baud_hint: int | None = None,
    civ_address: int | None = None,
    save_to_ini: bool = True,
) -> RadioConnection | None:
    """Find a radio, prompting when several are connected on an interactive console."""
    radios = find_radios(
        ini_path, port_hint=port_hint, baud_hint=baud_hint,
        civ_address=civ_address, save_to_ini=save_to_ini,
    )
    if not radios:
        return None
    if len(radios) == 1:
        return radios[0]

    print("More than one radio responded:")
    for index, radio in enumerate(radios, 1):
        if sys.platform == "darwin":
            port_label = f"serial device {index}"
        elif sys.platform.startswith("linux"):
            port_label = Path(radio.port).name
        else:
            port_label = radio.port
        print(f"{index}. {radio.model_name} on {port_label}")
    selection = 1
    if sys.stdin.isatty():
        try:
            entered = input(f"Select a radio [1-{len(radios)}]: ").strip()
            if entered:
                selection = int(entered)
        except (EOFError, ValueError):
            selection = 1
    if not 1 <= selection <= len(radios):
        selection = 1
    chosen = radios[selection - 1]
    for radio in radios:
        if radio is not chosen:
            radio.close()
    return chosen


def _profile_section_name(radio: RadioConnection) -> str:
    model = radio.model_id.casefold()
    if radio.protocol == "CI-V":
        address = radio.civ_address if radio.civ_address is not None else 0
        base = f"ci-v-{address:02x}"
    elif model in {"0761", "0840"}:
        base = f"yaesu-{model}"
    elif model:
        base = f"cat-{model}"
    else:
        base = "cat-unknown"
    return f"radio:{base}"


def _save_connection(ini_path: Path, radio: RadioConnection, port_info: Any) -> None:
    """Create or update this radio's profile, leaving [yac] preferences alone."""
    contents = ini_path.read_text(encoding="utf-8-sig") if ini_path.exists() else ""
    lines = contents.splitlines(keepends=True)
    sections = _radio_profiles(ini_path)
    target = _profile_section_name(radio)
    # Match by protocol/model (or CI-V address) and USB serial when known. This
    # upgrades the starter profiles while allowing same-model USB radios with
    # distinct hardware serials to acquire separate profiles.
    radio_id = radio.model_id.casefold()
    for profile in sections:
        same_radio = (
            profile.get("protocol", "").casefold() == radio.protocol.casefold()
            and (
                profile.get("model_id", "").casefold() == radio_id
                or (radio.protocol == "CI-V" and profile.get("civ_address", "").casefold()
                    in {f"0x{radio.civ_address:02x}", f"{radio.civ_address:02x}"})
            )
        )
        old_usb = profile.get("usb_identity", "")
        if same_radio and (not old_usb or not radio.usb_identity or old_usb == radio.usb_identity):
            target = profile["_section"]
            break
    if radio.usb_identity and any(
        p.get("_section", "").casefold() == target.casefold()
        and p.get("usb_identity") not in (None, "", radio.usb_identity)
        for p in sections
    ):
        target += "-" + re.sub(r"[^a-z0-9]+", "-", radio.usb_identity.casefold()).strip("-")

    platform_key = f"port_hint_{_platform_name()}"
    updates = {
        "protocol": radio.protocol,
        "model": radio.model_name,
        "model_id": radio.model_id,
        platform_key: radio.port,
        "baud_rate": str(radio.baudrate),
    }
    if radio.civ_address is not None:
        updates["civ_address"] = f"0x{radio.civ_address:02X}"
    if radio.usb_identity:
        updates["usb_identity"] = radio.usb_identity

    start = end = None
    in_target = False
    for index, line in enumerate(lines):
        section = re.match(r"^[ \t]*\[([^\]]+)\]", line.rstrip("\r\n"))
        if section:
            if in_target:
                end = index
                break
            in_target = section.group(1).casefold() == target.casefold()
            if in_target:
                start = index
    if start is None:
        newline = "\r\n" if "\r\n" in contents else "\n"
        if lines and not lines[-1].endswith(("\n", "\r")):
            lines[-1] += newline
        if lines and lines[-1].strip():
            lines.append(newline)
        lines.append(f"[{target}]{newline}")
        lines.extend(f"{key}={value}{newline}" for key, value in updates.items())
    else:
        if end is None:
            end = len(lines)
        newline = "\r\n" if "\r\n" in contents else "\n"
        seen: set[str] = set()
        rewritten: list[str] = []
        for line in lines[start + 1:end]:
            ending = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
            match = re.match(r"^([ \t]*)([^=:#]+?)[ \t]*=", line.rstrip("\r\n"))
            key = match.group(2).strip().casefold() if match else ""
            if key in updates:
                rewritten.append(f"{key}={updates[key]}{ending or newline}")
                seen.add(key)
            else:
                rewritten.append(line)
        rewritten.extend(f"{key}={value}{newline}" for key, value in updates.items() if key not in seen)
        lines[start + 1:end] = rewritten

    ini_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="", dir=ini_path.parent,
            prefix=f".{ini_path.name}.", suffix=".tmp", delete=False,
        ) as temporary:
            temporary.write("".join(lines))
            temp_path = Path(temporary.name)
        os.replace(temp_path, ini_path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def _read_label(root: Path, language: str, label_id: str, fallback: str) -> str:
    try:
        return (root / "lang" / language / "labels" / label_id).read_text(
            encoding="utf-8-sig"
        ).strip()
    except OSError:
        return fallback


def _clear_console() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def main() -> int:
    parser = argparse.ArgumentParser(description="Find a transceiver on serial ports.")
    parser.add_argument("--ini", type=Path, help="INI file (defaults to project yac.ini)")
    parser.add_argument("--port", default="", help="Try this COM port first")
    parser.add_argument("--baud", type=int, help="Try this baud rate first")
    parser.add_argument("--civ-address", help="Try an Icom CI-V address first, e.g. A4")
    args = parser.parse_args()

    address = None
    if args.civ_address:
        try:
            address = int(args.civ_address, 0)
        except ValueError:
            try:
                address = int(args.civ_address, 16)
            except ValueError:
                parser.error("--civ-address must be hexadecimal, such as A4 or 0xA4")

    ini_path = (args.ini or project_root() / "yac.ini").expanduser().resolve()
    values = _config_values(ini_path)
    language = values.get("lang", "en") or "en"
    radio = find_radio(
        ini_path, port_hint=args.port, baud_hint=args.baud, civ_address=address
    )
    root = project_root()
    if radio is None:
        print(_read_label(root, language, "l049", "Not Available"))
        return 1

    _clear_console()
    print(_read_label(root, language, "l008", "Radio Connected"))
    print(f"{radio.model_name} connected.")
    radio.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
