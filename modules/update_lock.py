"""Coordinate YAC and its updater across supported platforms."""
from contextlib import contextmanager
import sys


@contextmanager
def application_lock(root, exclusive=False):
    if sys.platform == 'win32':
        import msvcrt
        root.mkdir(parents=True, exist_ok=True)
        # Windows uses a single exclusive byte lock for controller or updater.
        with (root / '.update.lock').open('a+b') as handle:
            handle.seek(0, 2)
            if handle.tell() == 0:
                handle.write(b'0')
                handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise RuntimeError('Close YAC or the other updater before continuing.') from None
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return
    if sys.platform not in {'linux', 'darwin'}:
        yield
        return
    import fcntl
    root.mkdir(parents=True, exist_ok=True)
    with (root / '.update.lock').open('a') as handle:
        try:
            fcntl.flock(handle, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Close YAC or the other updater before continuing.') from None
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
