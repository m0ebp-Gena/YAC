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
            audio_setup.control(yac,ROOT,'en',iter(['c','e','q']).__next__)
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
            audio_setup.control(yac,ROOT,'en',iter(['e','q']).__next__)
        save.assert_not_called()
        sd.RawInputStream.assert_not_called()
