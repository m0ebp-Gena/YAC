"""Bounded, thread-safe decoded text; never pass terminal escape codes through."""
from threading import Lock


class RestoreError(ValueError):
    """The original radio settings could not be confirmed after capture."""


class TextBuffer:
    def __init__(self, limit=10000):
        self.limit = limit
        self.text = ''
        self.pending = ''
        self.lock = Lock()

    def append(self, value):
        value = ''.join(c for c in value if c in '\n\t' or 32 <= ord(c) < 127)
        with self.lock:
            self.text = (self.text + value)[-self.limit:]
            self.pending = (self.pending + value)[-self.limit:]

    def snapshot(self):
        with self.lock:
            return self.text

    def take(self):
        with self.lock:
            result, self.pending = self.pending, ''
            return result

    def clear(self):
        with self.lock:
            self.text = self.pending = ''
