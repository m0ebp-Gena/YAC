import json
from pathlib import Path
import struct
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, MagicMock, patch

import yac
from modules import audio_setup

ROOT = Path(__file__).resolve().parents[1]


def device(name, channels=2):
    return dict(name=name, max_input_channels=channels, hostapi=0)


class AudioSetupTests(unittest.TestCase):
    def test_successful_enter_saves_and_returns_without_an_extra_key(self):
        for enter in ('\r', '\n'):
            sd = self.backend()
            with patch.dict('sys.modules', {'sounddevice': sd}), \
                 patch.object(yac, '_read_settings', return_value={}), \
                 patch.object(yac, '_set_yac_value') as save, \
                 patch('modules.chat_int.show_response') as say:
                audio_setup.control(yac, ROOT, 'en', iter(['.', enter]).__next__)
            self.assertEqual(save.call_count, 2)
            self.assertEqual(say.call_args.args[0], yac._read_label(ROOT, 'en', 'l290', ''))
            sd.RawInputStream.assert_not_called()

    def test_enter_returns_to_decoder_menu(self):
        from modules.decoder_control import DecoderManager
        sd = self.backend()
        manager = DecoderManager(yac, ROOT, SimpleNamespace(), 'en')
        with patch.dict('sys.modules', {'sounddevice': sd}), \
             patch.object(yac, '_read_settings', return_value={}), \
             patch.object(yac, '_set_yac_value') as save, \
             patch('modules.chat_int.show_response'), \
             patch('modules.chat_int.show_back') as back:
            manager.control(iter(['a', '.', '\r', 'q']).__next__)
        self.assertEqual(save.call_count, 2)
        back.assert_called_once_with(ROOT, 'en')
        sd.RawInputStream.assert_not_called()

    def test_failed_enter_stays_in_selection_without_saving(self):
        sd = self.backend()
        sd.check_input_settings.side_effect = ValueError('Unsupported format')
        keys = Mock(side_effect=['.', '\r', 'q'])
        with patch.dict('sys.modules', {'sounddevice': sd}), \
             patch.object(yac, '_read_settings', return_value={}), \
             patch.object(yac, '_set_yac_value') as save, \
             patch('modules.chat_int.show_response'), \
             patch('modules.audio_setup.LOG.exception'):
            audio_setup.control(yac, ROOT, 'en', keys)
        self.assertEqual(keys.call_count, 3)
        save.assert_not_called()

    def windows_backend(self):
        hosts = [{'name': n} for n in ['MME', 'Windows DirectSound', 'Windows WASAPI']]
        devices = []
        for host, names in enumerate([
                ['Microsoft Sound Mapper - Input', 'Laptop Microphone Array (Intel', 'Microphone (USB Audio CODEC)'],
                ['Primary Sound Capture Driver', 'Laptop Microphone Array (Intel Audio)', 'Microphone (USB Audio CODEC)'],
                ['Laptop Microphone Array (Intel Audio)', 'Microphone (USB Audio CODEC)']]):
            for name in names:
                devices.append(dict(name=name, max_input_channels=2, hostapi=host))
        return SimpleNamespace(query_devices=Mock(return_value=devices),
                               query_hostapis=Mock(return_value=hosts),
                               check_input_settings=Mock(), RawInputStream=MagicMock())

    def test_windows_plain_list_has_full_names_without_interface_duplicates(self):
        sd = self.windows_backend()
        with patch.object(audio_setup.sys, 'platform', 'win32'):
            chosen = audio_setup.normal_inputs(audio_setup.inputs(sd))
        self.assertEqual([d['name'] for d in chosen],
                         ['Laptop Microphone Array (Intel Audio)', 'Microphone (USB Audio CODEC)'])
        self.assertEqual([d['index'] for d in chosen], [6, 7])
        sd.RawInputStream.assert_not_called()

    def test_saved_old_interface_is_retained_without_duplicate_same_name(self):
        sd = self.windows_backend()
        identity = json.dumps({'name': 'Microphone (USB Audio CODEC)', 'host': 'MME'})
        with patch.object(audio_setup.sys, 'platform', 'win32'):
            saved = audio_setup.resolve(sd, identity)
            chosen = audio_setup.normal_inputs(audio_setup.inputs(sd), saved)
        self.assertEqual(len(chosen), 2)
        self.assertEqual(chosen[1]['host'], 'MME')
        self.assertEqual(chosen[1]['index'], 2)

    def test_unmatched_saved_name_is_not_guessed_or_lost(self):
        sd = self.windows_backend()
        identity = json.dumps({'name': 'Laptop Microphone Array (Intel', 'host': 'MME'})
        with patch.object(audio_setup.sys, 'platform', 'win32'):
            saved = audio_setup.resolve(sd, identity)
            chosen = audio_setup.normal_inputs(audio_setup.inputs(sd), saved)
        self.assertIn(saved, chosen)
        self.assertEqual(saved['name'], 'Laptop Microphone Array (Intel')

    def test_no_wasapi_uses_one_available_interface_without_default_alias(self):
        sd = self.windows_backend()
        sd.query_devices.return_value = sd.query_devices.return_value[:6]
        with patch.object(audio_setup.sys, 'platform', 'win32'):
            chosen = audio_setup.normal_inputs(audio_setup.inputs(sd))
        self.assertEqual(len(chosen), 2)
        self.assertTrue(all(d['host'] == 'Windows DirectSound' for d in chosen))
        self.assertNotIn('Primary Sound Capture Driver', [d['name'] for d in chosen])

    def test_saved_device_opens_plain_list_without_opening_or_saving_audio(self):
        sd = self.windows_backend()
        identity = json.dumps({'name': 'Microphone (USB Audio CODEC)', 'host': 'MME'})
        with patch.object(audio_setup.sys, 'platform', 'win32'), \
             patch.dict('sys.modules', {'sounddevice': sd}), \
             patch.object(yac, '_read_settings', return_value={'cw_audio_identity': identity, 'cw_audio_channel': '2'}), \
             patch.object(yac, '_set_yac_value') as save, \
             patch('modules.chat_int.show_response') as say:
            audio_setup.control(yac, ROOT, 'en', iter(['q']).__next__)
        text = '\n'.join(c.args[0] for c in say.call_args_list)
        self.assertIn('Microphone (USB Audio CODEC)', text)
        self.assertIn('ch 2/2', text)
        for technical in ['MME', 'WASAPI', 'DirectSound', 'Advanced']:
            self.assertNotIn(technical, text)
        save.assert_not_called()
        sd.RawInputStream.assert_not_called()

    def test_non_windows_inputs_keep_their_order(self):
        sd = self.windows_backend()
        all_devices = audio_setup.inputs(sd)
        with patch.object(audio_setup.sys, 'platform', 'linux'):
            self.assertEqual(audio_setup.normal_inputs(all_devices), all_devices)

    def test_plain_windows_selection_saves_exact_device_without_starting_capture(self):
        sd = self.windows_backend()
        with patch.object(audio_setup.sys, 'platform', 'win32'), \
             patch.dict('sys.modules', {'sounddevice': sd}), \
             patch.object(yac, '_read_settings', return_value={}), \
             patch.object(yac, '_set_yac_value') as save, \
             patch('modules.chat_int.show_response'):
            audio_setup.control(yac, ROOT, 'en', iter(['.', '.', '\r', 'q']).__next__)
        sd.check_input_settings.assert_called_once_with(device=7, channels=1,
                                                       dtype='float32', samplerate=48000)
        identity = json.loads(save.call_args_list[1].args[2])
        self.assertEqual(identity, {'name': 'Microphone (USB Audio CODEC)', 'host': 'Windows WASAPI'})
        sd.RawInputStream.assert_not_called()

    def backend(self, devices=None):
        return SimpleNamespace(query_devices=Mock(return_value=devices or [device('Speakers',0),device('Radio')]),
                               query_hostapis=Mock(return_value=[{'name':'WASAPI'}]),
                               check_input_settings=Mock(), RawInputStream=MagicMock())

    def test_identity_survives_reordering_without_default_fallback(self):
        saved=json.dumps({'name':'Radio','host':'WASAPI'})
        sd=self.backend([device('Radio')])
        self.assertEqual(audio_setup.resolve(sd,saved)['index'],0)
        sd.query_devices.return_value=[device('Mic'),device('Radio')]
        self.assertEqual(audio_setup.resolve(sd,saved)['index'],1)
        for devices in ([device('Mic')],[device('Radio'),device('Radio')]):
            sd.query_devices.return_value=devices
            with self.assertRaises(ValueError): audio_setup.resolve(sd,saved)
        sd.RawInputStream.assert_not_called()

    def test_level_reads_only_requested_channel_and_closes(self):
        sd=self.backend()
        stream=sd.RawInputStream.return_value.__enter__.return_value
        stream.read.return_value=(struct.pack('<ffff',0,0.5,0,0.5),False)
        value,clipping=audio_setup.level(sd,1,2)
        self.assertEqual(value,50)
        self.assertFalse(clipping)
        sd.RawInputStream.assert_called_once_with(device=1,channels=2,dtype='float32',samplerate=48000,blocksize=960)
        sd.RawInputStream.return_value.__exit__.assert_called_once()

    def test_browse_cancel_never_opens_or_saves(self):
        sd=self.backend([device('Mic'),device('Radio')])
        with patch.dict('sys.modules',{'sounddevice':sd}), \
             patch.object(yac,'_read_settings',return_value={}), \
             patch.object(yac,'_set_yac_value') as save, \
             patch('modules.chat_int.show_response'),patch('modules.chat_int.show_back'):
            audio_setup.control(yac,ROOT,'en',iter(['.','c','q']).__next__)
        save.assert_not_called()
        sd.RawInputStream.assert_not_called()

    def test_explicit_save_uses_identity_and_format_check_without_capture(self):
        sd=self.backend()
        with patch.dict('sys.modules',{'sounddevice':sd}), \
             patch.object(yac,'_read_settings',return_value={}), \
             patch.object(yac,'_set_yac_value') as save, \
             patch('modules.chat_int.show_response'),patch('modules.chat_int.show_back'):
            audio_setup.control(yac,ROOT,'en',iter(['c','\r','q']).__next__)
        self.assertEqual(save.call_args_list[0].args[1:],('cw_audio_channel','2'))
        identity=save.call_args_list[1].args[2]
        self.assertEqual(json.loads(identity),{'name':'Radio','host':'WASAPI'})
        sd.RawInputStream.assert_not_called()
        sd.check_input_settings.assert_called_once()

    def test_unplug_before_save_preserves_configuration(self):
        sd=self.backend()
        sd.query_devices.side_effect=[[device('Radio')],[device('Mic')]]
        with patch.dict('sys.modules',{'sounddevice':sd}), \
             patch.object(yac,'_read_settings',return_value={}), \
             patch.object(yac,'_set_yac_value') as save, \
             patch('modules.chat_int.show_response'),patch('modules.chat_int.show_back'), \
             patch('modules.audio_setup.LOG.exception'):
            audio_setup.control(yac,ROOT,'en',iter(['\n','q']).__next__)
        save.assert_not_called()
        sd.RawInputStream.assert_not_called()

    def test_entry_announces_confirmation_and_echo_does_not_save(self):
        sd=self.backend()
        with patch.dict('sys.modules',{'sounddevice':sd}), \
             patch.object(yac,'_read_settings',return_value={}), \
             patch.object(yac,'_set_yac_value') as save, \
             patch('modules.chat_int.show_response') as say:
            audio_setup.control(yac,ROOT,'en',iter(['e','q']).__next__)
        save.assert_not_called()
        texts=[call.args[0] for call in say.call_args_list]
        self.assertIn('Enter: Save',texts)
        self.assertIn('q: Cancel',texts)
        sd.RawInputStream.assert_not_called()
        for lang in ('en','de','es','pl'):
            for token in ('l398','l399'):
                label=yac._read_label(ROOT,lang,token,'')
                self.assertTrue(label)
                self.assertLessEqual(len(label),15)
