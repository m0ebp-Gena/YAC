"""Validate build rotation using temporary files, without building a release."""
import tempfile
import unittest
from pathlib import Path

from modules.build_outputs import publish


class BuildOutputsTests(unittest.TestCase):
    def setUp(self):
        test_root = Path(__file__).resolve().parents[1] / 'builds/.work/test-runs'
        test_root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=test_root, ignore_cleanup_errors=True)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        assert self.root.resolve().is_relative_to(test_root.resolve())
        self.staging = self.root / 'builds/.work'
        self.staging.mkdir(parents=True)

    def staged(self, name, text):
        path = self.staging / name
        path.write_text(text)
        return path

    def test_new_date_archives_complete_previous_latest(self):
        publish(self.root, '2026-10-11', [self.staged('demo.zip', 'old demo')])
        publish(self.root, '2026-10-11', [self.staged('source.zip', 'old source')])
        latest = self.root
        publish(self.root, '2026-10-12', [self.staged('demo.zip', 'new demo')])
        previous = self.root / 'previous-builds/2026-10-11'
        self.assertEqual((previous/'source.zip').read_text(), 'old source')
        self.assertEqual((previous/'demo.zip').read_text(), 'old demo')
        self.assertEqual((latest/'demo.zip').read_text(), 'new demo')
        self.assertFalse((latest/'source.zip').exists())

    def test_same_date_replacement_preserves_each_run(self):
        for text in ('first','second','third'):
            publish(self.root, '2026-10-12', [self.staged('demo.zip', text)])
        previous = self.root/'previous-builds/2026-10-12'
        self.assertEqual((previous/'demo.zip').read_text(), 'first')
        self.assertEqual((previous/'002/demo.zip').read_text(), 'second')
        self.assertEqual((self.root/'demo.zip').read_text(), 'third')

    def test_missing_or_outside_artifact_leaves_latest_untouched(self):
        publish(self.root, '2026-10-11', [self.staged('demo.zip', 'keep')])
        with self.assertRaises(FileNotFoundError):
            publish(self.root, '2026-10-12', [self.staging/'missing.zip'])
        outside = self.root/'outside.zip'
        outside.write_text('outside')
        with self.assertRaises(ValueError):
            publish(self.root, '2026-10-12', [outside])
        self.assertEqual((self.root/'demo.zip').read_text(), 'keep')
        self.assertFalse((self.root/'previous-builds').exists())

    def test_zip_checksum_and_runnable_directory_publish_together(self):
        demo = self.staging/'YAC'
        demo.mkdir()
        (demo/'demo.exe').write_bytes(b'placeholder, never executed')
        outputs = publish(self.root, '2026-10-12', [self.staged('demo.zip','zip'),
                          self.staged('demo.sha256','hash'), demo])
        self.assertEqual(len(outputs), 3)
        self.assertTrue((self.root/'builds/runnable/YAC/demo.exe').is_file())

    def test_rotation_leaves_project_files_and_unrelated_zips_in_root(self):
        (self.root/'yac.py').write_text('project code')
        (self.root/'reference.zip').write_text('unrelated archive')
        publish(self.root, '2026-10-11', [self.staged('demo.zip', 'old')])
        publish(self.root, '2026-10-12', [self.staged('demo.zip', 'new')])
        self.assertEqual((self.root/'yac.py').read_text(), 'project code')
        self.assertEqual((self.root/'reference.zip').read_text(), 'unrelated archive')
