import configparser
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import pi_audio

spec = importlib.util.spec_from_file_location('pi_audio_helper', Path(__file__).resolve().parents[1] / 'pi/audio-settings.py')
backend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backend)


class PiAudioTests(unittest.TestCase):
    def config(self, **settings):
        result = configparser.ConfigParser(interpolation=None)
        result['launcher'] = {'yac_command': '/my/yac', 'volume': '70', **settings}
        return result

    def test_discovers_named_playback_devices_and_survives_reordering(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            card = base / 'card2'
            card.mkdir()
            (card / 'id').write_text('USB_Speaker\n')
            (card / 'pcm0p').mkdir()
            (card / 'pcm1c').mkdir()
            expected = [pi_audio.Output('USB_Speaker', 0, 'USB_Speaker')]
            self.assertEqual(pi_audio.outputs(base), expected)
            card.rename(base / 'card0')
            self.assertEqual(pi_audio.outputs(base), expected)

    def test_saved_device_skips_prompt_but_reapplies_system_default(self):
        output = pi_audio.Output('USB', 0, 'USB')
        config = self.config(audio_setup_complete='yes', audio_card='USB', audio_device='0')
        with patch.object(pi_audio, 'outputs', return_value=[output]), patch.object(pi_audio, 'helper') as helper:
            self.assertTrue(pi_audio.setup(config, Path('unused')))
            helper.assert_called_once_with('apply', card='USB', device=0, volume=70)

    def test_braille_mode_never_probes_or_changes_audio(self):
        with patch.object(pi_audio, 'outputs') as detect, patch.object(pi_audio, 'helper') as helper:
            self.assertTrue(pi_audio.setup(self.config(access_mode='braille'), Path('unused')))
            detect.assert_not_called()
            helper.assert_not_called()

    def test_missing_saved_device_cycles_and_only_saves_confirmed_output(self):
        choices = [pi_audio.Output('HDMI', 0, 'HDMI'), pi_audio.Output('USB', 0, 'USB')]
        config = self.config(audio_setup_complete='yes', audio_card='missing', audio_device='0')
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(pi_audio, 'outputs', return_value=choices), \
             patch.object(pi_audio.sys.stdin, 'isatty', return_value=True), \
             patch.object(pi_audio, 'helper') as helper:
            path = Path(folder) / 'launcher.ini'
            calls = []
            def say(item, words, deadline):
                calls.append(item.card)
                return item.card == 'USB'
            self.assertTrue(pi_audio.setup(config, path, say=say))
            self.assertEqual(calls, ['HDMI', 'USB'])
            saved = configparser.ConfigParser()
            saved.read(path)
            self.assertEqual(saved['launcher']['audio_card'], 'USB')
            self.assertEqual(saved['launcher']['yac_command'], '/my/yac')
            self.assertEqual(helper.call_args_list[-1].args, ('end',))

    def test_timeout_restores_speech_requests_shutdown_and_never_saves(self):
        with patch.object(pi_audio, 'outputs', return_value=[]), \
             patch.object(pi_audio.sys.stdin, 'isatty', return_value=True), \
             patch.object(pi_audio, 'helper') as helper, \
             patch.object(pi_audio, 'save') as save, \
             patch.object(pi_audio.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)) as run:
            self.assertFalse(pi_audio.setup(self.config(), Path('unused'), clock=iter([0, 301]).__next__))
            save.assert_not_called()
            self.assertEqual([call.args for call in helper.call_args_list], [('begin',), ('end',)])
            self.assertEqual(run.call_args.args[0][-1], 'poweroff')

    def test_cancel_restores_speech_without_saving_or_shutdown(self):
        choice = pi_audio.Output('USB', 0, 'USB')
        with patch.object(pi_audio, 'outputs', return_value=[choice]), \
             patch.object(pi_audio.sys.stdin, 'isatty', return_value=True), \
             patch.object(pi_audio, 'helper') as helper, \
             patch.object(pi_audio, 'save') as save:
            def cancel(*args):
                raise KeyboardInterrupt
            with self.assertRaises(KeyboardInterrupt):
                pi_audio.setup(self.config(), Path('unused'), say=cancel)
            self.assertEqual(helper.call_args.args, ('end',))
            save.assert_not_called()

    def test_helper_rejects_injection_unconnected_device_and_extra_fields(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            for request in [dict(action='apply', card='USB"\n', device=0, volume=70),
                            dict(action='apply', card='USB', device=0, volume=70),
                            dict(action='end', path='/tmp/anything')]:
                with self.assertRaises(ValueError):
                    backend.validate(request, base)

    def test_helper_refuses_unmanaged_config_and_rolls_back_restart_failure(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(backend, 'ALSA', Path(folder) / 'asound.conf'), \
             patch.object(backend, 'run') as run:
            backend.ALSA.write_text('personal settings')
            with self.assertRaises(ValueError):
                backend.apply('USB', 0)
            self.assertEqual(backend.ALSA.read_text(), 'personal settings')
            backend.ALSA.unlink()
            run.side_effect = [subprocess.CalledProcessError(1, 'systemctl'), None]
            with self.assertRaises(subprocess.CalledProcessError):
                backend.apply('USB', 0)
            self.assertFalse(backend.ALSA.exists())


if __name__ == '__main__':
    unittest.main()
