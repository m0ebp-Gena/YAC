"""IC-705 receive-only RTTY text on its companion USB serial interface."""
import threading
from modules.decoder_text import RestoreError


def companion(radio, ports, configured=''):
    from modules.find_rad import _usb_pair_keys
    primary = next((p for p in ports if p.device == radio.port), None)
    if primary is None:
        raise ValueError('Cannot identify radio USB ports')
    keys = set(_usb_pair_keys(primary))
    matches = [p for p in ports if p.device != radio.port and keys and
               keys.intersection(_usb_pair_keys(p))]
    if configured:
        matches = [p for p in matches if p.device == configured]
    if len(matches) != 1:
        raise ValueError('Radio companion port is ambiguous')
    return matches[0].device


class IcomRTTY:
    def __init__(self, yac, radio, output, settings):
        self.yac, self.radio, self.output, self.settings = yac, radio, output, settings
        self.serial = None
        self.previous = None
        self.restore_needed = False
        self.error = None
        self.stopping = threading.Event()
        self.worker = None

    def setting(self, number, value=None):
        payload = b'\x05' + bytes.fromhex(number)
        if value is not None:
            response = self.yac._civ_send(self.radio, 0x1A, payload + bytes([value]))
            ack = bytes([254,254,224,self.radio.civ_address,251,253])
            if ack not in response:
                raise ValueError('Decoder setting rejected')
        response = self.yac._civ_send(self.radio, 0x1A, payload)
        marker = bytes([254,254,224,self.radio.civ_address,0x1A]) + payload
        index = response.find(marker)
        if index < 0:
            raise ValueError('Decoder setting unreadable')
        tail = response[index + len(marker):]
        if len(tail) < 2 or tail[1] != 253:
            raise ValueError('Invalid decoder setting')
        if value is not None and tail[0] != value:
            raise ValueError('Decoder setting readback failed')
        return tail[0]

    def start(self):
        if self.radio.model_id.casefold() != 'ic-705':
            raise ValueError('Unsupported RTTY decoder')
        if self.yac._current_mode_code(self.radio) not in (4, 8):
            raise ValueError('Select RTTY mode first')
        import serial
        from serial.tools import list_ports
        from modules.find_rad import _open_serial
        port = companion(self.radio, list(list_ports.comports()), self.settings.get('rtty_port', ''))
        # Refuse any port-B SEND/keying assignment before opening the device.
        for number in ('0125', '0126', '0127'):
            if self.setting(number) in (3, 4):
                raise ValueError('USB B is assigned to SEND or keying')
        previous = self.setting('0133')
        if previous not in (0, 1):
            raise ValueError('USB B is in use for another function')
        self.previous = previous
        try:
            self.serial = _open_serial(port, 9600, serial)
            self.serial.timeout = 0
            self.serial.reset_input_buffer()
            if previous != 1:
                # Even an unacknowledged write may have changed the radio.
                self.restore_needed = True
                self.setting('0133', 1)
            self.worker = threading.Thread(target=self._run, daemon=True)
            self.worker.start()
        except Exception:
            self.close()
            raise

    def _run(self):
        while not self.stopping.wait(0.02):
            try:
                count = self.serial.in_waiting
                if count:
                    text = self.serial.read(min(count, 4096)).decode('ascii', errors='replace')
                    self.output.append(text.replace('\r', '\n'))
            except (OSError, ValueError) as error:
                self.error = str(error)
                return

    def close(self):
        self.stopping.set()
        if self.worker:
            self.worker.join(timeout=1)
        close_error = None
        if self.serial:
            try:
                self.serial.close()
            except (ValueError, OSError) as error:
                close_error = error
            self.serial = None
        previous, self.previous = self.previous, None
        if previous is not None and self.restore_needed:
            self.restore_needed = False
            try:
                self.setting('0133', previous)
            except (ValueError, OSError) as error:
                raise RestoreError('USB B function restoration unconfirmed') from error
        if close_error:
            raise close_error
