"""Receive-speed reseeding, quiet interaction and retained session selection."""
import io
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import yac
from modules import chat_int, help_int
from modules.cw_audio import AudioCW, ToneDecoder
from modules.decoder_control import DecoderManager
from modules.decoder_text import TextBuffer

ROOT = Path(__file__).resolve().parents[1]


def receiver(output, wpm=20):
    session = AudioCW(output, {})
    session.initial_wpm = wpm
    session.decoder = ToneDecoder(output, 650, 0.025, wpm)
    return session


class DecoderSpeedTests(unittest.TestCase):
    def test_read_and_limit_do_not_reset_adapted_timing(self):
        for wpm, direction in [(5, -1), (60, 1), (20, 0)]:
            session = receiver(TextBuffer(), wpm)
            decoder = session.decoder
            decoder.timing.mark(0.08)
            self.assertEqual(session.speed(direction), wpm)
            self.assertIs(session.decoder, decoder)
            self.assertEqual(len(decoder.timing.pending), 1)

    def test_adjustment_reseeds_live_decoder_without_clearing_text_or_audio(self):
        output = TextBuffer()
        output.append('CQ ')
        session = receiver(output)
        session.stream = object()
        stream = session.stream
        session.decoder.timing.mark(0.06)
        self.assertEqual(session.speed(1), 21)
        self.assertAlmostEqual(session.decoder.timing.unit, 1.2 / 21)
        self.assertEqual(session.decoder.timing.pending, [])
        self.assertEqual((session.decoder.pitch, session.decoder.threshold), (650, 0.025))
        self.assertIs(session.stream, stream)
        self.assertEqual(output.snapshot(), 'CQ ')
        self.assertEqual(session.speed(-1), 20)
        # Explicit seed changes retain the adaptive timing algorithm.
        for mark in [0.04, 0.12] * 8:
            session.decoder.timing.mark(mark)
            session.decoder.timing.space(0.04)
        self.assertAlmostEqual(session.decoder.timing.unit, 0.04)
        self.assertEqual(session.speed(), 20)  # Selected seed, not an unmeasured speed claim.

    def test_fractional_saved_estimate_moves_to_adjacent_whole_speed(self):
        self.assertEqual(receiver(TextBuffer(), 20.5).speed(1), 21)
        self.assertEqual(receiver(TextBuffer(), 20.5).speed(-1), 20)

    def manager(self):
        manager = DecoderManager(yac, ROOT, SimpleNamespace(), 'en')
        manager.kind = 'c'
        manager.session = receiver(manager.buffer, 23)
        return manager

    def test_direct_speed_verify_review_and_exit(self):
        manager = self.manager()
        session = manager.session
        manager.buffer.append('A' * 60 + 'LATEST')
        keys = iter(['.', '.', ',', 'v', 'r', ',', '.', 'q', 'v', 'q'])
        with patch.object(chat_int, 'show_response') as say, \
             patch.object(yac, '_radio_status', return_value='S 7 7.030000 CW') as status:
            manager.decoder_view('c', keys.__next__)
        spoken = [call.args[0] for call in say.call_args_list]
        self.assertEqual(status.call_count, 2)
        self.assertEqual(spoken.count('Decode Spd 24 WPM'), 2)
        self.assertNotIn('Decode Spd 25 WPM', spoken)
        self.assertIn('S 7 7.030000 CW', spoken)
        self.assertEqual(spoken.count('LATEST'), 2)
        self.assertIn('A' * 60, spoken)
        self.assertEqual(manager.audio_wpm, 24)
        self.assertIsNone(manager.session)
        self.assertTrue(session.stop_event.is_set())
        self.assertEqual(manager.buffer.snapshot(), 'A' * 60 + 'LATEST')

    def test_review_clear_and_quit_keep_capture_running(self):
        manager = self.manager()
        session = manager.session
        manager.view = True
        manager.buffer.append('CQ TEST')
        def read():
            self.assertFalse(manager.view)
            manager.buffer.append('NEW ')
            manager.tick()
            return next(keys)
        keys = iter(['c', '.', 'q'])
        manager.last_audio_check = float('inf')
        with patch.object(chat_int, 'show_response') as say, \
             patch.object(chat_int, 'show_stream') as stream:
            manager.cw_review(read)
        self.assertIs(manager.session, session)
        self.assertTrue(manager.view)
        self.assertFalse(session.stop_event.is_set())
        stream.assert_not_called()
        self.assertEqual(manager.buffer.snapshot(), 'NEW NEW ')
        self.assertIn(manager.label('l281'), [c.args[0] for c in say.call_args_list])

    def test_native_decoder_does_not_offer_speed_but_verifies_radio(self):
        manager = self.manager()
        manager.session = SimpleNamespace(close=lambda: None)
        with patch.object(chat_int, 'show_response') as say, \
             patch.object(yac, '_radio_status', return_value='S 5 7.030000 CW'):
            manager.decoder_view('c', iter(['.', 'v', 'q']).__next__)
        spoken = [c.args[0] for c in say.call_args_list]
        self.assertEqual(spoken.count(manager.label('l129')), 2)
        self.assertIn('S 5 7.030000 CW', spoken)

    def test_stopped_speed_is_retained_for_restart(self):
        manager = self.manager()
        manager.audio_wpm = 23
        with patch.object(chat_int, 'show_response'), \
             patch.object(yac, '_radio_status', return_value='S 5 7.030000 CW'):
            manager.decoder_view('c', iter(['s', '.', 'v', 'q']).__next__)
        self.assertEqual(manager.audio_wpm, 24)

    def test_cw_and_review_use_same_help_rtty_uses_its_own(self):
        manager = self.manager()
        with patch.object(chat_int, 'show_response') as say:
            manager.decoder_view('c', iter(['h', 'r', 'h', 'q', 'q']).__next__)
        spoken = [c.args[0] for c in say.call_args_list]
        self.assertEqual(spoken.count(help_int.get_help(ROOT, 'en', 'h052')), 2)
        with patch.object(chat_int, 'show_response') as say:
            manager.decoder_view('r', iter(['h', 'q']).__next__)
        self.assertIn(help_int.get_help(ROOT, 'en', 'h053'), [c.args[0] for c in say.call_args_list])

    def test_restarted_audio_uses_session_choice_without_writing_ini(self):
        radio = SimpleNamespace(protocol='CAT', model_id='0840')
        manager = DecoderManager(yac, ROOT, radio, 'en')
        manager.audio_wpm = 27
        saved = {'cw_audio_device': '0', 'cw_audio_wpm': '20'}
        with patch.object(yac, '_read_settings', return_value=saved), \
             patch.object(yac, '_current_mode_code', return_value='3'), \
             patch('modules.mic_gain.profile', return_value={}), \
             patch.object(DecoderManager, 'radio_pitch', return_value=600), \
             patch('modules.cw_audio.AudioCW') as audio:
            audio.return_value.speed.return_value = 27
            manager.start('c', clear=False)
        self.assertEqual(audio.call_args.args[1]['cw_audio_wpm'], '27')
        self.assertEqual(saved['cw_audio_wpm'], '20')

    def test_cw_history_survives_restart_and_other_decoder(self):
        radio = SimpleNamespace(protocol='CAT', model_id='ic-705')
        manager = DecoderManager(yac, ROOT, radio, 'en')
        manager.buffer.append('CW HISTORY')
        with patch.object(yac, '_read_settings', return_value={'cw_audio_device': '0'}), \
             patch.object(yac, '_current_mode_code', return_value='3'), \
             patch('modules.mic_gain.profile', return_value={}), \
             patch.object(DecoderManager, 'radio_pitch', return_value=600), \
             patch('modules.cw_audio.AudioCW') as audio, \
             patch('modules.rtty_decode.IcomRTTY'):
            audio.return_value.speed.return_value = 20
            manager.start('c')
            manager.stop()
            manager.start('r')
            manager.buffer.append('RTTY HISTORY')
            manager.pending = 'RTTY PENDING'
            manager.start('c')
        self.assertEqual(manager.buffer.snapshot(), 'CW HISTORY')
        self.assertEqual(manager.pending, '')
        self.assertEqual(manager.rtty_buffer.snapshot(), 'RTTY HISTORY')

    def test_short_translated_help_and_label_are_present(self):
        for language in ['en', 'de', 'es', 'pl']:
            text = help_int.get_help(ROOT, language, 'h052')
            self.assertTrue(text.endswith('***'))
            self.assertIn('5', text)
            self.assertIn('60', text)
            label = chat_int.label(ROOT, language, 'l431')
            self.assertIn('{value}', label)
            self.assertLessEqual(len(label.replace('{value}', '')), 15)


if __name__ == '__main__':
    unittest.main()
