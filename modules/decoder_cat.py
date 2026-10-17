"""One serial reader for Kenwood CAT replies and unsolicited CW characters."""
from collections import deque
import threading
import time


class CATStream:
    def __init__(self, radio, output):
        self.radio, self.output = radio, output
        self.lock = threading.RLock()
        self.partial = b''
        self.replies = deque(maxlen=100)
        self.error = None
        self.stopping = threading.Event()
        self.worker = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.worker.start()

    def feed(self, data):
        self.partial += data
        while b';' in self.partial:
            frame, self.partial = self.partial.split(b';', 1)
            if frame.startswith(b'CD2'):
                self.output.append(frame[3:].decode('ascii', errors='replace'))
            else:
                self.replies.append(frame.decode('ascii', errors='ignore') + ';')
        if len(self.partial) > 4096:
            self.partial = b''
            self.error = 'CAT frame overflow'

    def poll(self):
        with self.lock:
            count = self.radio.serial.in_waiting
            if count:
                self.feed(self.radio.serial.read(min(count, 4096)))

    def exchange(self, command):
        with self.lock:
            self.poll()
            self.replies.clear()  # Preserve decoded text and partial frames.
            self.radio.serial.write(command.encode('ascii'))
            self.radio.serial.flush()
            prefix = command[:3] if command.startswith('CD') else command[:2]
            deadline = time.monotonic() + 0.8
            while time.monotonic() < deadline:
                self.poll()
                for reply in list(self.replies):
                    if reply.startswith(prefix) or reply in ('?;', 'E;'):
                        self.replies.remove(reply)
                        return reply.upper()
                time.sleep(0.005)
            return ''

    def _run(self):
        while not self.stopping.wait(0.02):
            try:
                self.poll()
            except (OSError, ValueError) as error:
                self.error = str(error)
                return

    def close(self):
        self.stopping.set()
        if self.worker.is_alive():
            self.worker.join(timeout=1)
