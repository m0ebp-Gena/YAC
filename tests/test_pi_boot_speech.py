import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


boot = load('pi_boot_speech', 'pi/boot-speech.py')
launcher = load('pi_launcher_boot_test', 'pi-launcher.py')
audio = load('pi_boot_audio_test', 'pi/audio-settings.py')


class BootWaitTests(unittest.TestCase):
    def test_wait_accepts_completed_boot_even_with_failed_unrelated_unit(self):
        import subprocess
        for state, code in [('running', 0), ('degraded', 1)]:
            with patch.object(launcher.subprocess, 'run', return_value=subprocess.CompletedProcess([], code, state + '\n')) as run:
                launcher.wait_for_boot()
                self.assertEqual(run.call_args.args[0], ['/usr/bin/systemctl', 'is-system-running', '--wait'])
                self.assertEqual(run.call_args.kwargs['timeout'], 90)

    def test_wait_rejects_unfinished_boot(self):
        import subprocess
        with patch.object(launcher.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, 'starting\n')):
            with self.assertRaises(RuntimeError):
                launcher.wait_for_boot()

    def test_launcher_waits_before_unmuting_speech(self):
        events = []
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(launcher.Path, 'home', return_value=Path(folder)), \
             patch.object(launcher.sys, 'platform', 'linux'), \
             patch.object(launcher, 'wait_for_boot', side_effect=lambda: events.append('boot-finished')), \
             patch.object(launcher.pi_audio, 'helper', side_effect=lambda action: events.append(action)):
            self.assertEqual(launcher.main(), 1)
        self.assertEqual(events, ['boot-finished', 'ready'])


class BootSpeechTests(unittest.TestCase):
    def setUp(self):
        waiting = patch.object(launcher, 'wait_for_boot')
        waiting.start()
        self.addCleanup(waiting.stop)

    def test_boot_wait_failure_restores_speech_and_does_not_start_yac(self):
        with patch.object(launcher.sys, 'platform', 'linux'), \
             patch.object(launcher, 'wait_for_boot', side_effect=RuntimeError('still booting')), \
             patch.object(launcher.pi_audio, 'helper') as helper, \
             patch.object(launcher.pi_audio, 'setup') as setup:
            self.assertEqual(launcher.main(), 1)
        helper.assert_called_once_with('ready')
        setup.assert_not_called()

    def test_saved_braille_mode_mutes_even_without_the_boot_mute_dropin(self):
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(audio, 'SILENT', Path(folder) / 'silent'), \
             patch.object(audio, 'run') as run:
            audio.finish_boot('ready-braille')
            self.assertEqual(audio.SILENT.read_text(), '7\n')
            self.assertIn('yac-boot-speech-recovery.timer', run.call_args.args[0])
            audio.finish_boot('ready')
            self.assertEqual(audio.SILENT.read_text(), '6\n')

    def test_mute_flushes_and_only_runs_once_per_boot(self):
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(boot, 'MARKER', Path(folder) / 'marker'), \
             patch.object(boot, 'SILENT', Path(folder) / 'silent'), \
             patch.object(boot.subprocess, 'run') as run:
            boot.mute()
            self.assertEqual(boot.SILENT.read_text(), '7\n')
            boot.SILENT.write_text('6\n')
            boot.mute()
            self.assertEqual(boot.SILENT.read_text(), '6\n')
            run.assert_called_once()

    def test_speech_ready_keeps_recovery_until_audio_setup_completes(self):
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(audio, 'SILENT', Path(folder) / 'silent'), \
             patch.object(audio, 'run') as run:
            audio.finish_boot('ready')
            run.assert_not_called()
            audio.finish_boot('complete')
            run.assert_called_once()

    def test_failed_service_start_still_clears_boot_mute(self):
        import subprocess
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(boot, 'SILENT', Path(folder) / 'silent'), \
             patch.object(boot.subprocess, 'run', side_effect=subprocess.TimeoutExpired('systemctl', 20)):
            boot.SILENT.write_text('7\n')
            with self.assertRaises(subprocess.TimeoutExpired):
                boot.recover()
            self.assertEqual(boot.SILENT.read_text(), '6\n')

    def test_recovery_starts_backend_and_clears_both_mute_bits(self):
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(boot, 'SILENT', Path(folder) / 'silent'), \
             patch.object(boot.subprocess, 'run') as run:
            boot.recover()
            self.assertEqual(boot.SILENT.read_text(), '6\n')
            self.assertEqual(run.call_args.args[0][-2:], ['start', 'espeakup.service'])

    def test_missing_yac_restores_speech_before_error(self):
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(launcher.Path, 'home', return_value=Path(folder)), \
             patch.object(launcher.sys, 'platform', 'linux'), \
             patch.object(launcher.pi_audio, 'helper') as helper:
            self.assertEqual(launcher.main(), 1)
            helper.assert_called_once_with('ready')

    def test_invalid_ini_restores_speech_before_error(self):
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(launcher.Path, 'home', return_value=Path(folder)), \
             patch.object(launcher.sys, 'platform', 'linux'), \
             patch.object(launcher.pi_audio, 'helper') as helper:
            config = Path(folder) / '.config/yac/pi-launcher.ini'
            config.parent.mkdir(parents=True)
            config.write_text('[launcher]\nvolume=bad\n')
            self.assertEqual(launcher.main(), 1)
            helper.assert_called_once_with('ready')

    def test_braille_startup_cancels_recovery_without_unmuting(self):
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(launcher.Path, 'home', return_value=Path(folder)), \
             patch.object(launcher.sys, 'platform', 'linux'), \
             patch.object(launcher.pi_audio, 'helper') as helper:
            config = Path(folder) / '.config/yac/pi-launcher.ini'
            config.parent.mkdir(parents=True)
            config.write_text('[launcher]\naccess_mode=braille\n')
            self.assertEqual(launcher.main(), 1)
            helper.assert_called_once_with('ready-braille')


if __name__ == '__main__':
    unittest.main()
