"""Offline tone-entry and command regression tests; no serial hardware."""
import io
import os
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import yac
from modules import lang_sel, name_call_sel
from modules.find_rad import RadioConnection

ROOT = Path(__file__).resolve().parent


def radio(model="IC-705"):
    return RadioConnection(None, "mock", 38400, "CI-V" if model == "IC-705" else "CAT",
                           model, model, civ_address=0xA4 if model == "IC-705" else None)


class ToneInput(unittest.TestCase):
    def edit(self, selection, keys, initial=""):
        with patch.object(os, "name", "nt"), patch.object(name_call_sel, "_read_edit_key", side_effect=keys), redirect_stdout(io.StringIO()):
            return yac._edit_tone(selection, initial)

    def test_restricted_fields_and_lengths(self):
        self.assertEqual(self.edit("CTCSS", list("1x00..04") + ["enter"]), ("enter", "100.0"))
        self.assertEqual(self.edit("DCS N", list("D0.237") + ["enter"]), ("enter", "023"))
        self.assertEqual(self.edit("DCS I", ["0", "2", "4", "backspace", "3", "enter"]), ("enter", "023"))

    def test_navigation_and_immediate_commands(self):
        self.assertEqual(self.edit("CTCSS", ["8", "8", "5", "left", ".", "enter"]), ("enter", "88.5"))
        self.assertEqual(self.edit("DCS N", ["0", "2", "3", "home", "delete", "0", "enter"]), ("enter", "023"))
        for key in ["i", "h", "q"]:
            self.assertEqual(self.edit("CTCSS", ["8", "8", key]), (key, "88"))

    def test_validation_and_leading_zero(self):
        for selection in ["DCS N", "DCS I"]:
            for value in ["023", "754"]:
                self.assertEqual(yac._tone_value(value, True, selection), (selection, value))
            for value in ["23", "0023", "888", "000", "023.0", "D023"]:
                self.assertIsNone(yac._tone_value(value, True, selection))
            self.assertIsNone(yac._tone_value("023", False, selection))
        self.assertEqual(yac._tone_value("88.5", False, "CTCSS"), ("CTCSS", "88.5"))
        for value in ["88.55", "88..5", "88,5", "nan", "88.6"]:
            self.assertIsNone(yac._tone_value(value, True, "CTCSS"))

    def control(self, edits, keys, setter=None, model="IC-705"):
        output = io.StringIO()
        with patch.object(yac, "_edit_tone", side_effect=edits) as edit, patch.object(lang_sel, "read_key", side_effect=keys), patch.object(yac, "_set_tone", side_effect=setter) as setting, redirect_stdout(output):
            yac._tone_control(ROOT, radio(model), "en", "Test")
        return output.getvalue(), edit, setting

    def test_cycle_loops_and_q_does_not_write(self):
        output, edit, setting = self.control([("i", "88.5"), ("i", "023"), ("i", "754"), ("q", "")], [])
        self.assertEqual([c.args[0] for c in edit.call_args_list], ["CTCSS", "DCS N", "DCS I", "CTCSS"])
        self.assertEqual([c.args[1] for c in edit.call_args_list], [""] * 4)
        setting.assert_not_called()

    def test_help_retains_value_and_target_then_returns(self):
        output, edit, setting = self.control([("h", "88.5"), ("enter", "88.5")], ["h", "x", "t"], lambda *a: "CTCSS 88.5 Hz TX")
        self.assertEqual(edit.call_args_list[1].args, ("CTCSS", "88.5"))
        self.assertIn("TX/Both: t/b", output)
        self.assertIn("transmission only", output)
        self.assertEqual(setting.call_args.args[3:], ("88.5", "TX", "CTCSS"))
        self.assertEqual(setting.call_count, 1)

    def test_both_inverted_and_failed_setting_can_retry(self):
        edits = [("i", ""), ("i", ""), ("enter", "023"), ("enter", "025")]
        results = iter(["Tone change failed.", "DCS I 025 Both"])
        output, edit, setting = self.control(edits, ["b", "b"], lambda *a: next(results))
        self.assertEqual(edit.call_args_list[-1].args, ("DCS I", "023"))
        self.assertEqual(setting.call_args.args[3:], ("025", "Both", "DCS I"))

    def test_empty_enter_and_cancel_target_do_not_write(self):
        _, _, setting = self.control([("enter", ""), ("enter", "88.5")], ["q"])
        setting.assert_not_called()

    def test_invalid_code_stays_in_field_without_target_prompt(self):
        output, edit, setting = self.control([("i", ""), ("enter", "888"), ("q", "888")], [])
        self.assertIn("Invalid tone/code", output)
        self.assertNotIn("TX/Both", output)
        setting.assert_not_called()

    def test_ctcss_only_cycles_ctcss(self):
        _, edit, setting = self.control([("i", ""), ("q", "")], [], model="0761")
        self.assertEqual([c.args[0] for c in edit.call_args_list], ["CTCSS", "CTCSS"])
        setting.assert_not_called()

    def test_ftx1_dcs_applies_both_without_target_prompt(self):
        for selection, edits in [("DCS N", [("i", ""), ("enter", "023")]), ("DCS I", [("i", ""), ("i", ""), ("enter", "023")])]:
            output, _, setting = self.control(edits, [], lambda *a: f"{selection} 023 Both", model="0840")
            self.assertNotIn("TX/Both: t/b", output)
            setting.assert_called_once()
            self.assertEqual(setting.call_args.args[4:], ("Both", selection))

    def test_icom_polarity_bytes_and_tx_preserves_rx(self):
        for selection, target, initial, expected in [("DCS N", "Both", 0, 0), ("DCS I", "Both", 0, 0x11), ("DCS N", "TX", 0x11, 1), ("DCS I", "TX", 0, 0x10)]:
            with self.subTest(selection=selection, target=target):
                sent = []
                def send(r, command, data):
                    sent.append((command, data))
                    return bytes.fromhex("FEFEE0A4FBFD")
                def exchange(r, command, sub):
                    data = bytes([0x03 if target == "Both" else 0x06]) if command == 0x16 else bytes([expected if sent else initial, 0, 0x23])
                    return bytes([0xFE, 0xFE, 0xE0, 0xA4, command, sub]) + data + b"\xfd"
                with patch.object(yac, "_civ_send", side_effect=send), patch.object(yac, "_civ_exchange", side_effect=exchange):
                    self.assertTrue(yac._tone_command(radio(), "ic705", selection, "023", target))
                self.assertEqual(sent[0], (0x1B, bytes([0x02, expected, 0, 0x23])))

    def test_ftx1_polarity_templates_and_readback(self):
        for selection, polarity in [("DCS N", 0), ("DCS I", 1)]:
            sent = []
            def exchange(r, command):
                sent.append(command)
                return command[:-1] + str(polarity) + ";" if command in {"EX010323;", "EX010324;"} else "CN01000;" if command == "CN01;" else "CT03;" if command == "CT0;" else ""
            with patch.object(yac, "_yaesu_vfo_side", 0), patch.object(yac, "_cat_exchange", side_effect=exchange):
                self.assertTrue(yac._tone_command(radio("0840"), "ftx1", selection, "023", "Both"))
            self.assertIn(f"EX010323{polarity};", sent)
            self.assertIn(f"EX010324{polarity};", sent)
        with patch.object(yac, "_cat_exchange", return_value="?;") as cat:
            self.assertFalse(yac._tone_command(radio("0840"), "ftx1", "DCS I", "023", "Both"))
            self.assertNotIn("CT03;", [c.args[1] for c in cat.call_args_list])

    def test_failed_readback_is_not_success(self):
        with patch.object(yac, "_civ_send", return_value=bytes.fromhex("FEFEE0A4FBFD")), patch.object(yac, "_civ_exchange", return_value=b""):
            self.assertFalse(yac._tone_command(radio(), "ic705", "DCS I", "023", "Both"))

    def test_selected_type_reaches_radio_and_confirmation_is_localized(self):
        with patch.object(yac, "_current_frequency", return_value="145.5"), patch.object(yac, "_current_mode", return_value="FM"), patch.object(yac, "_tone_command", return_value=True) as command:
            for lang, both in [("en", "Both"), ("de", "Beide"), ("pl", "Oba")]:
                self.assertEqual(yac._set_tone(ROOT, radio(), lang, "023", "Both", "DCS I"), f"DCS I 023 {both}")
                self.assertEqual(command.call_args.args[2:], ("DCS I", "023", "Both"))
            command.reset_mock()
            self.assertIn("Invalid", yac._set_tone(ROOT, radio(), "en", "888", "Both", "DCS N"))
            command.assert_not_called()

    def test_wrong_mode_prevents_radio_write(self):
        with patch.object(yac, "_current_frequency", return_value="145.5"), patch.object(yac, "_current_mode", return_value="USB"), patch.object(yac, "_tone_command") as command:
            self.assertIn("FM", yac._set_tone(ROOT, radio(), "en", "88.5", "TX", "CTCSS"))
            command.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
