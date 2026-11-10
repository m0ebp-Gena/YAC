from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from modules import nexus_ft8
from modules.decoder_control import DecoderManager
import yac


ROOT = Path(__file__).resolve().parents[1]


class NexusAudioChannelTests(unittest.TestCase):
    def test_macos_arm64_uses_engine_input_and_excludes_radio_playback(self):
        app = Mock()
        app._read_label.return_value = 'Decoder Started'
        app._read_settings.return_value = {
            'ft_audio_input': 'USB Audio Device', 'call': 'N0CALL', 'ft_grid': 'IO91',
            'ft_distance': '300', 'ft_distance_unit': 'mi',
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            engine = root / nexus_ft8.MACOS_ARM64_ENGINE
            engine.parent.mkdir(parents=True)
            engine.touch()
            manager = DecoderManager(app, root, SimpleNamespace(model_id='demo'), 'en')
            with patch.object(nexus_ft8.sys, 'platform', 'darwin'), \
                 patch.object(nexus_ft8.platform, 'machine', return_value='arm64'), \
                 patch.object(nexus_ft8, 'audio_devices', side_effect=[
                     ['USB Audio Device', 'MacBook Air Microphone'],
                     ['USB Audio Device', 'MacBook Air Speakers'],
                 ]), patch.object(nexus_ft8, 'NexusReceive') as receiver:
                self.assertEqual(manager.start('f'), 'Decoder Started')
                self.assertEqual(receiver.call_args.args[1:4],
                                 (engine, 'USB Audio Device', 'MacBook Air Speakers'))
                self.assertIsNone(receiver.call_args.kwargs['input_channel'])
                self.assertEqual(manager.ft_distance, (300, 'mi'))

    def test_linux_arm64_uses_bundled_engine_when_path_is_blank(self):
        app = Mock()
        app._read_label.return_value = 'Decoder Started'
        app._read_settings.return_value = {
            'ft_audio_input': 'plughw:CARD=Device,DEV=0',
            'call': 'N0CALL', 'ft_grid': 'IO91',
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            engine = root / nexus_ft8.LINUX_ARM64_ENGINE
            engine.parent.mkdir(parents=True)
            engine.touch()
            manager = DecoderManager(app, root, SimpleNamespace(model_id='demo'), 'en')
            with patch('modules.decoder_control.sys.platform', 'linux'), \
                 patch('modules.nexus_ft8.platform.machine', return_value='aarch64'), \
                 patch.object(nexus_ft8, 'audio_devices', side_effect=[
                     ['plughw:CARD=Device,DEV=0'],
                     ['plughw:CARD=Device,DEV=1', 'default', 'plughw:CARD=Headphones,DEV=0'],
                 ]), \
                 patch.object(nexus_ft8, 'NexusReceive') as receiver:
                self.assertEqual(manager.start('f'), 'Decoder Started')
                self.assertEqual(receiver.call_args.args[1], engine)
                self.assertEqual(receiver.call_args.args[3], 'plughw:CARD=Headphones,DEV=0')

    def test_linux_ft_decoder_requires_explicit_engine_input(self):
        engine = ROOT / 'modules/nexus_ft8.py'
        settings = {'ft_engine': str(engine), 'ft_audio_output': 'plughw:CARD=Headphones,DEV=0',
                    'call': 'N0CALL', 'ft_grid': 'IO91', 'cw_audio_channel': '2'}
        manager = DecoderManager(yac, ROOT, SimpleNamespace(model_id='demo'), 'en')
        with patch('modules.decoder_control.sys.platform', 'linux'), \
             patch.object(yac, '_read_settings', return_value=settings), \
             patch.object(nexus_ft8, 'NexusReceive') as receiver:
            self.assertEqual(manager.start('f'), 'Audio input not set')
            receiver.assert_not_called()

            settings['ft_audio_input'] = 'plughw:CARD=CODEC,DEV=0'
            self.assertEqual(manager.start('f'), 'Decoder Started')
            self.assertEqual(receiver.call_args.args[1:4],
                             (engine, settings['ft_audio_input'], settings['ft_audio_output']))
            self.assertIsNone(receiver.call_args.kwargs['input_channel'])
            receiver.return_value.start.assert_called_once()

    def test_ft_decoder_uses_saved_channel_of_multichannel_input(self):
        device = {'name': 'Radio USB Audio', 'channels': 2}
        engine = 'modules/nexus_ft8.py'  # Existing file for the preflight path check.
        settings = {'cw_audio_identity': 'saved input', 'ft_engine': engine,
                    'ft_audio_output': 'PC Speakers', 'call': 'N0CALL', 'ft_grid': 'IO91'}
        for channel in (1, 2, 3):
            with self.subTest(channel=channel):
                manager = DecoderManager(yac, ROOT, SimpleNamespace(model_id='demo'), 'en')
                with patch('modules.decoder_control.sys.platform', 'win32'), \
                     patch.dict('sys.modules', sounddevice=Mock()), \
                     patch.object(yac, '_read_settings', return_value=dict(settings, cw_audio_channel=str(channel))), \
                     patch('modules.audio_setup.resolve', return_value=device), \
                     patch.object(nexus_ft8, 'NexusReceive') as receiver:
                    if channel <= device['channels']:
                        self.assertEqual(manager.start('f'), 'Decoder Started')
                        self.assertEqual(receiver.call_args.kwargs['input_channel'], channel)
                        receiver.return_value.start.assert_called_once()
                    else:
                        self.assertEqual(manager.start('f'), 'Saved audio channel unavailable')
                        receiver.assert_not_called()

    def test_old_engine_refuses_channel_selection_before_capture(self):
        path = Path('jimmy-engine-host.exe')
        result = subprocess.CompletedProcess([], 0, 'Radio USB Audio\n')
        with patch.object(nexus_ft8.subprocess, 'run', return_value=result) as run, \
             patch.object(nexus_ft8.subprocess, 'Popen') as start:
            receiver = nexus_ft8.NexusReceive(Mock(), path, 'Radio USB Audio', 'PC Speakers',
                                              'N0CALL', 'IO91', input_channel=2)
            with self.assertRaisesRegex(RuntimeError, 'does not support selecting'):
                receiver.start()
            self.assertEqual(run.call_args.args[0], [str(path), '--list-devices', '--yac-channel-support'])
            start.assert_not_called()


if __name__ == '__main__':
    unittest.main()
