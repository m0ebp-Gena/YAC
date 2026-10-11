"""Read-only connection checks, called solely from the terminal input loop."""
import logging
import time

LOG = logging.getLogger('yac')


def reconnect_same_radio(radio):
    """Probe only the original device and model, without restoring any settings."""
    import serial
    from serial.tools import list_ports
    from modules import find_rad
    ports = list(list_ports.comports())
    if radio.usb_identity:
        ports = [p for p in ports if find_rad._usb_identity(p) == radio.usb_identity]
    else:
        ports = [p for p in ports if p.device == radio.port]
    profile = {'port_hint': radio.port, 'baud_rate': str(radio.baudrate),
               'protocol': radio.protocol, 'model_id': radio.model_id,
               'usb_identity': radio.usb_identity,
               'civ_address': hex(radio.civ_address or 0)}
    found = find_rad._probe_saved_profiles([profile], ports, serial)
    if not found:
        return False
    replacement = found[0]
    radio.serial = replacement.serial
    radio.port = replacement.port
    radio.port_details = replacement.port_details
    return True


class ConnectionWatch:
    def __init__(self, radio, read_frequency, announce, reconnect=reconnect_same_radio,
                 clock=time.monotonic, interval=5.0):
        self.radio = radio
        self.read_frequency = read_frequency
        self.announce = announce
        self.reconnect = reconnect
        self.clock = clock
        self.interval = interval
        self.next_check = clock() + interval
        self.frequency = None
        self.failures = 0
        self.lost = False

    def tick(self):
        if self.radio.is_dummy or self.clock() < self.next_check:
            return
        self.next_check = self.clock() + self.interval
        try:
            if self.lost and not self.reconnect(self.radio):
                return
            frequency = self.read_frequency()
            if frequency is None:
                raise OSError('No valid frequency response')
        except Exception:
            LOG.debug('Connection check failed port=%s', self.radio.port, exc_info=True)
            self.failures += 1
            if self.lost or self.failures >= 3:
                try:
                    self.radio.close()
                except Exception:
                    LOG.debug('Closing unavailable port failed', exc_info=True)
                if not self.lost:
                    self.lost = True
                    self.announce('lost')
            return
        self.failures = 0
        if self.lost:
            self.lost = False
            self.announce('restored')
        # Keep polling quiet: live state is read again by each user command.
        self.frequency = frequency
