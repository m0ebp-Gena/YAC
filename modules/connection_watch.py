"""Read-only connection checks, called solely from the terminal input loop."""
import logging
import time

LOG = logging.getLogger('yac')


class RecoveryExpired(Exception):
    """Unwind any active control so its normal shutdown can close resources."""


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
                 clock=time.monotonic, interval=5.0, recovery_timeout=60.0,
                 read_recovery_state=None):
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
        self.recovery_timeout = recovery_timeout
        self.recovery_deadline = None
        self.read_recovery_state = read_recovery_state or read_frequency
        self.expired = False

    def report_error(self):
        if self.radio.is_dummy:
            return False
        if not self.lost:
            self.lost = True
            self.recovery_deadline = self.clock() + self.recovery_timeout
            self.next_check = self.clock() + self.interval
            try:
                self.radio.close()
            except Exception:
                LOG.debug('Closing unavailable port failed', exc_info=True)
            self.announce('lost')
        return True

    def _check_deadline(self):
        if self.lost and self.recovery_deadline is not None and self.clock() >= self.recovery_deadline:
            if not self.expired:
                self.expired = True
                self.announce('aborting')
            raise RecoveryExpired

    def tick(self):
        self._check_deadline()
        if self.radio.is_dummy or self.clock() < self.next_check:
            return
        self.next_check = self.clock() + self.interval
        try:
            if self.lost and not self.reconnect(self.radio):
                self._check_deadline()
                return
            self._check_deadline()
            frequency = self.read_recovery_state() if self.lost else self.read_frequency()
            self._check_deadline()
            if frequency is None:
                raise OSError('No valid frequency response')
        except RecoveryExpired:
            raise
        except Exception:
            LOG.debug('Connection check failed port=%s', self.radio.port, exc_info=True)
            self.failures += 1
            if self.lost or self.failures >= 3:
                if self.lost:
                    try:
                        self.radio.close()
                    except Exception:
                        LOG.debug('Closing unavailable port failed', exc_info=True)
                else:
                    self.report_error()
            self._check_deadline()
            return
        self.failures = 0
        if self.lost:
            self.lost = False
            self.recovery_deadline = None
            self.announce('restored')
        # Keep polling quiet: live state is read again by each user command.
        self.frequency = frequency
