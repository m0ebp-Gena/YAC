"""Radio errors start recovery; timeout unwinds and closes YAC normally."""
import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

import yac
from modules import connection_watch, lang_sel
from modules.dummy_radio import create_dummy_radio

ROOT=Path(__file__).resolve().parents[1]


class RadioRecoveryTests(unittest.TestCase):
    def test_command_failure_starts_recovery_without_duplicate_message(self):
        radio=create_dummy_radio()
        radio.is_dummy=False
        radio._yac_connection_watch=Mock()
        radio._yac_connection_watch.report_error.return_value=True
        with patch.object(yac,'_cat_exchange',return_value='?;'):
            self.assertEqual(yac._radio_status(ROOT,radio,'en'),'')
        radio._yac_connection_watch.report_error.assert_called_once()

    def test_timeout_announces_abort_and_closes_radio_in_all_languages(self):
        for language in ('en','de','es','pl'):
            with self.subTest(language=language):
                radio=create_dummy_radio();radio.is_dummy=False
                now=[0]
                actual_watch=connection_watch.ConnectionWatch
                def factory(radio,read,announce,**kwargs):
                    watch=actual_watch(radio,lambda:None,announce,
                              reconnect=lambda radio:False,clock=lambda:now[0],**kwargs)
                    watch.report_error()
                    return watch
                def read_key(idle_callback=None):
                    now[0]=60
                    idle_callback()
                    self.fail('timeout did not unwind input')
                with patch.object(yac,'connect_radio',return_value=radio), \
                     patch.object(yac,'_read_settings',return_value={'lang':language,'call':'test'}), \
                     patch.object(connection_watch,'ConnectionWatch',side_effect=factory), \
                     patch.object(lang_sel,'read_key',side_effect=read_key),redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(yac.main([]),1)
                for token in ('l050','l109','l367'):
                    self.assertEqual(output.getvalue().splitlines().count(yac._read_label(ROOT,language,token,'')),1)
                self.assertFalse(radio.serial.is_open)
                self.assertFalse(hasattr(radio,'_yac_connection_watch'))
