import io
from pathlib import Path
import unittest
from contextlib import redirect_stdout
from modules import quit_control

ROOT = Path(__file__).resolve().parents[1]


class QuitTests(unittest.TestCase):
    def confirm(self, keys):
        with redirect_stdout(io.StringIO()) as output:
            result = quit_control.confirm(ROOT, 'en', iter(keys).__next__)
        return result, output.getvalue()

    def test_yes_confirms(self):
        self.assertTrue(self.confirm(['Y'])[0])

    def test_no_and_q_cancel(self):
        for key in ['N', 'q']:
            result, text = self.confirm([key])
            self.assertFalse(result)
            self.assertIn('Quit cancelled', text)

    def test_other_commands_and_enter_do_not_confirm(self):
        self.assertFalse(self.confirm(['', '\n', 'w', 'n'])[0])

    def test_interruption_cancels(self):
        for error in [EOFError, KeyboardInterrupt, OSError, RuntimeError]:
            def fail():
                raise error()
            with redirect_stdout(io.StringIO()):
                self.assertFalse(quit_control.confirm(ROOT, 'en', fail))

    def test_all_languages_explain_literal_confirmation_keys(self):
        from modules import chat_int
        for language in ['en', 'de', 'es', 'pl']:
            label = chat_int.label(ROOT, language, 'l352')
            for key in ['y', 'n', 'q']:
                self.assertIn(key, label)
