"""Public downloads contain documentation, not private testing templates."""
from pathlib import Path
import unittest

from modules.package_layout import documents


class PackageLayoutTests(unittest.TestCase):
    def test_both_platforms_exclude_owner_templates_and_keep_user_guides(self):
        root = Path(__file__).resolve().parents[1]
        for platform in ('win', 'mac-linux'):
            files = documents(root, platform)
            self.assertTrue(files)
            self.assertFalse(any('checklist' in path.name or path.name.endswith('-template.txt')
                                 for path in files))
            self.assertTrue(any(path.name.startswith('START-HERE') for path in files))
        self.assertTrue((root / 'doc/checklists/checklist-core-template.txt').is_file())
        self.assertTrue((root / 'doc/checklists/checklist-radio-template.txt').is_file())
