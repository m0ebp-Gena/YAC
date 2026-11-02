"""Main Verify includes active lock state without changing the radio."""
import unittest
from pathlib import Path
from unittest.mock import patch
import yac
from modules import lock_control, verify_settings
from modules.dummy_radio import create_dummy_radio
from tests import test_lock_control
ROOT=Path(__file__).resolve().parents[1]
class VerifyLockTests(unittest.TestCase):
    def test_main_verify_omits_off_and_reads_live_on(self):
        radio=create_dummy_radio()
        with patch.object(yac,'_cat_exchange',wraps=yac._cat_exchange) as exchange:
            self.assertNotIn('Lock',verify_settings.verify(yac,ROOT,radio,'en'))
            radio.serial.lock='1'
            self.assertIn('Lock On',verify_settings.verify(yac,ROOT,radio,'en'))
        self.assertEqual(radio.serial.lock,'1')
        self.assertEqual([c.args[1] for c in exchange.call_args_list if c.args[1].startswith('LK')],['LK;','LK;'])
    def test_native_dial_and_panel_labels_are_read_only(self):
        for scope,expected in [(0,'Dial Lock'),(1,'Panel Lock')]:
            radio,state,writes,read,send=test_lock_control.LockTests().civ('IC-705','0063',1,scope)
            with patch.object(verify_settings,'catalog',return_value={}),patch.object(yac,'_civ_exchange',side_effect=read),patch.object(yac,'_civ_send',side_effect=send):
                self.assertEqual(verify_settings.verify(yac,ROOT,radio,'en'),expected)
            self.assertEqual(writes,[])
            self.assertEqual(state[bytes.fromhex('1650')],1)
    def test_unknown_is_not_silently_reported_as_off(self):
        radio=create_dummy_radio()
        with patch.object(verify_settings,'catalog',return_value={}),patch.object(yac,'_cat_exchange',return_value='?;') as exchange:
            self.assertEqual(verify_settings.verify(yac,ROOT,radio,'en'),'Lock Unknown')
        self.assertEqual([c.args[1] for c in exchange.call_args_list],['LK;'])
    def test_supported_off_is_omitted(self):
        radio=create_dummy_radio()
        self.assertEqual(lock_control.active_status(yac,ROOT,radio,'en'),'')
    def test_four_language_lock_labels_are_kept(self):
        radio=create_dummy_radio();radio.serial.lock='1'
        for language in ('en','de','es','pl'):
            label=(ROOT/f'lang/{language}/labels/l405').read_text(encoding='utf-8').strip()
            self.assertIn(label,verify_settings.verify(yac,ROOT,radio,language))
            self.assertLessEqual(len((ROOT/f'lang/{language}/labels/l411').read_text(encoding='utf-8').strip()),15)
if __name__=='__main__': unittest.main()
