"""Context help during frequency entry must not send a frequency command."""
import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import yac
from modules import help_int, lang_sel
from modules.dummy_radio import create_dummy_radio

ROOT = Path(__file__).resolve().parents[1]


class FrequencyEntryHelpTests(unittest.TestCase):
    def test_repeated_help_returns_to_input_before_apply_abort_or_invalid(self):
        for language in ('en', 'de', 'es', 'pl'):
            for value in ('', 'text', '14.185'):
                with self.subTest(language=language, value=value):
                    radio = create_dummy_radio()
                    original = radio.serial.frequency
                    keys = iter(['e', 'q', 'y'])
                    values = iter(['h', 'H', value])
                    output = io.StringIO()
                    def entered():
                        self.assertEqual(radio.serial.frequency, original)
                        return next(values)
                    with patch.object(yac, 'connect_radio', return_value=radio), patch.object(yac, '_read_settings', return_value={'call':'test', 'lang':language}), patch.object(lang_sel, 'read_key', side_effect=lambda: next(keys)), patch('builtins.input', side_effect=entered) as entry, patch.object(yac, '_set_frequency', wraps=yac._set_frequency) as setter, redirect_stdout(output):
                        self.assertEqual(yac.main([]), 0)
                    self.assertEqual(entry.call_count, 3)
                    setter.assert_called_once()
                    self.assertEqual(setter.call_args.args[3], value)
                    self.assertEqual(output.getvalue().count(help_int.get_help(ROOT, language, 'h033')), 2)
                    if value == '14.185':
                        self.assertEqual(radio.serial.frequency, 14185000)
                    else:
                        self.assertEqual(radio.serial.frequency, original)
                        label = 'l355' if not value else 'l356'
                        self.assertIn(yac._read_label(ROOT, language, label, ''), output.getvalue())

    def test_interrupt_after_help_returns_to_main_without_setting_frequency(self):
        radio = create_dummy_radio()
        keys = iter(['e', 'q', 'y'])
        with patch.object(yac, 'connect_radio', return_value=radio), patch.object(yac, '_read_settings', return_value={'call':'test', 'lang':'en'}), patch.object(lang_sel, 'read_key', side_effect=lambda: next(keys)), patch('builtins.input', side_effect=['h', EOFError]), patch.object(yac, '_set_frequency') as setter, redirect_stdout(io.StringIO()):
            self.assertEqual(yac.main([]), 0)
        setter.assert_not_called()
