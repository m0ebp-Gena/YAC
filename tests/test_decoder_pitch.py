"""Radio pitch readback, capture setup and silent live synchronization."""
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import yac
from modules.cw_audio import AudioCW, ToneDecoder
from modules.decoder_control import DecoderManager
from modules.decoder_text import TextBuffer
from modules.find_rad import RadioConnection

ROOT = Path(__file__).resolve().parents[1]


class DecoderPitchTests(unittest.TestCase):
    def manager(self):
        radio = RadioConnection(None, 'test', 115200, 'CAT', '0840', 'FTX-1')
        return DecoderManager(yac, ROOT, radio, 'en')

    def test_pitch_reads_real_radio_profile_without_setting_commands(self):
        manager = self.manager()
        with patch.object(yac, '_cat_exchange', return_value='KP37;') as exchange:
            self.assertEqual(manager.radio_pitch(), 670)
        exchange.assert_called_once_with(manager.radio, 'KP;')

    def test_start_overrides_saved_and_previous_pitch_on_every_restart(self):
        manager = self.manager()
        saved = {'cw_audio_device': '0', 'cw_audio_pitch_hz': '400'}
        with patch.object(yac, '_read_settings', return_value=saved), \
             patch.object(yac, '_current_mode_code', return_value='3'), \
             patch.object(yac, '_cat_exchange', side_effect=['KP37;', 'KP40;']) as exchange, \
             patch('modules.cw_audio.AudioCW') as audio:
            audio.return_value.speed.return_value = 20
            manager.start('c')
            self.assertEqual(audio.call_args.args[1]['cw_audio_pitch_hz'], '670')
            manager.stop()
            manager.start('c')
            self.assertEqual(audio.call_args.args[1]['cw_audio_pitch_hz'], '700')
        self.assertEqual(saved['cw_audio_pitch_hz'], '400')
        self.assertTrue(all(call.args[1] == 'KP;' for call in exchange.call_args_list))

    def test_unreadable_pitch_does_not_open_audio_or_guess(self):
        for reply in ('?;', 'KP99;', ''):
            manager = self.manager()
            with patch.object(yac, '_read_settings', return_value={'cw_audio_device': '0'}), \
                 patch.object(yac, '_current_mode_code', return_value='3'), \
                 patch.object(yac, '_cat_exchange', return_value=reply), \
                 patch('modules.cw_audio.AudioCW') as audio, \
                 self.assertLogs('yac', level='ERROR'):
                self.assertEqual(manager.start('c'), manager.label('l003'))
            audio.assert_not_called()

    def test_live_pitch_change_keeps_text_speed_and_adapted_timing(self):
        manager = self.manager()
        session = AudioCW(manager.buffer, {})
        session.initial_wpm = 23
        session.decoder = ToneDecoder(manager.buffer, 600, 0.025, 23)
        session.decoder.timing.mark(0.08)
        timing = session.decoder.timing
        manager.buffer.append('CQ ')
        manager.session, manager.kind = session, 'c'
        with patch.object(yac, '_current_mode_code', return_value='3'), \
             patch('modules.mic_gain.tx_state', return_value=False), \
             patch.object(yac, '_cat_exchange', return_value='KP40;'), \
             patch('modules.chat_int.show_response') as say:
            manager.tick()
        say.assert_not_called()
        self.assertEqual(session.decoder.pitch, 700)
        self.assertIs(session.decoder.timing, timing)
        self.assertEqual(timing.pending, [])
        self.assertEqual(session.speed(), 23)
        self.assertEqual(manager.buffer.snapshot(), 'CQ ')
        decoder = session.decoder
        session.set_pitch(700)
        self.assertIs(session.decoder, decoder)

    def test_unreadable_live_pitch_pauses_until_readback_recovers(self):
        manager = self.manager()
        session = SimpleNamespace(paused=False, error=None, set_pitch=lambda pitch: None)
        manager.session, manager.kind = session, 'c'
        with patch.object(yac, '_current_mode_code', return_value='3'), \
             patch('modules.mic_gain.tx_state', return_value=False), \
             patch.object(yac, '_cat_exchange', side_effect=['?;', 'KP30;']):
            with self.assertLogs('yac', level='ERROR'):
                manager.tick()
            self.assertTrue(session.paused)
            manager.last_audio_check = 0
            manager.tick()
            self.assertFalse(session.paused)


if __name__ == '__main__':
    unittest.main()
