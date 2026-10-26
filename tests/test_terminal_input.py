"""Queued adjustment keys must survive entry into raw terminal mode."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from modules import lang_sel

class TerminalInputTests(unittest.TestCase):
    def test_fast_adjustment_keys_are_not_flushed_between_reads(self):
        queued = list('..,,q')
        restored = []
        settings = [0, 1, 0, 0, 0, 0, []]
        terminal = SimpleNamespace(
            TCSANOW=0, TCSAFLUSH=2, TCSADRAIN=1,
            tcgetattr=lambda fd: settings[:],
            tcsetattr=lambda *args: restored.append(args),
        )
        def setraw(fd, when=terminal.TCSAFLUSH):
            if when == terminal.TCSAFLUSH:
                queued.clear()
        stream = SimpleNamespace(fileno=lambda: 10, isatty=lambda: True,
                                 read=lambda count: queued.pop(0) if queued else '')
        with patch.object(lang_sel.os, 'name', 'posix'), \
             patch.object(lang_sel.sys, 'stdin', stream), \
             patch.dict('sys.modules', {'termios': terminal, 'tty': SimpleNamespace(setraw=setraw)}):
            self.assertEqual([lang_sel.read_key() for _ in range(5)], list('..,,q'))
        self.assertEqual(len(restored), 5)
        self.assertTrue(all(call[1] == terminal.TCSADRAIN for call in restored))

if __name__ == '__main__':
    unittest.main()
