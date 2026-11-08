from pathlib import Path
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from experiments import nexus_ft8
from modules.decoder_control import DecoderManager
import yac


ROOT = Path(__file__).resolve().parents[1]


class NexusAudioChannelTests(unittest.TestCase):
    def test_ft_decoder_uses_saved_channel_of_multichannel_input(self):
        device = {'name': 'Radio USB Audio', 'channels': 2}
        engine = 'experiments/nexus_ft8.py'  # Existing file for the preflight path check.
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
