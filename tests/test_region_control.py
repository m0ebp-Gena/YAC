"""Region persistence and prevention of RF on receive-only frequencies."""
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import yac
from modules import ini_settings, region_control, region_plan, tuner_control
from tests.test_split_control import Cat, Civ

ROOT = Path(__file__).resolve().parents[1]


class RegionTests(unittest.TestCase):
    def test_default_and_strict_ini_validation(self):
        self.assertEqual(region_plan.selected({}), 1)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'yac.ini'
            for value in ('1', '2', '3'):
                path.write_text('[yac]\nregion=' + value, encoding='utf-8')
                self.assertEqual(region_plan.selected(ini_settings.read_settings(path)), int(value))
            for value in ('', '0', '4', 'Europe', '1.0'):
                path.write_text('[yac]\nregion=' + value, encoding='utf-8')
                with self.assertRaises(ini_settings.IniError):
                    ini_settings.read_settings(path)

    def test_control_reads_then_cycles_saves_and_returns_to_settings(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'yac.ini'
            before = '; keep\n[yac]\ncall=Test\nregion=3\n[radio]\nport=COM1\n'
            path.write_text(before, encoding='utf-8')
            proxy = SimpleNamespace(_read_settings=yac._read_settings,
                                    _set_yac_value=yac._set_yac_value,
                                    _read_label=lambda r, lang, token, fallback:
                                        yac._read_label(ROOT, lang, token, fallback))
            keys = iter(['r', 'r', 'h', 'q'])
            output = io.StringIO()
            with patch('modules.region_control.help_int.get_help', return_value='Region help'), \
                 redirect_stdout(output):
                region_control.control(proxy, root, 'en', lambda: next(keys))
            text = output.getvalue()
            self.assertLess(text.index('Region 3'), text.index('Region 1'))
            self.assertIn('Region 2', text)
            self.assertIn('Region help', text)
            self.assertEqual(ini_settings.read_settings(path)['region'], '2')
            self.assertIn('; keep', path.read_text())
            self.assertIn('[radio]\nport=COM1', path.read_text())
            original = path.read_bytes()
            with redirect_stdout(io.StringIO()):
                region_control.control(proxy, root, 'en', lambda: 'q')
            self.assertEqual(path.read_bytes(), original)

    def test_tables_have_distinct_edges_and_never_include_air_or_marine(self):
        for region in (1, 2, 3):
            for hz in (2182000, 4125000, 6215000, 8291000, 12290000,
                       16420000, 118000000, 121500000, 136975000,
                       156000000, 156800000, 162025000):
                self.assertFalse(region_plan.contains(ROOT, region, hz), (region, hz))
            self.assertTrue(region_plan.contains(ROOT, region, 14195000))
            for low, high in region_plan.load(ROOT, region)['transmit_ranges_hz']:
                self.assertTrue(region_plan.contains(ROOT, region, low))
                self.assertFalse(region_plan.contains(ROOT, region, high))
        self.assertFalse(region_plan.contains(ROOT, 1, 3900000))
        self.assertTrue(region_plan.contains(ROOT, 2, 3900000))
        self.assertFalse(region_plan.contains(ROOT, 3, 3900000))
        self.assertTrue(region_plan.contains(ROOT, 3, 3850000))
        for region in (1, 3):
            self.assertFalse(region_plan.contains(ROOT, region, 7250000))
        self.assertTrue(region_plan.contains(ROOT, 2, 7250000))
        self.assertFalse(region_plan.contains(ROOT, 2, 145795000))

    def test_yaesu_all_models_checks_actual_tx_vfo_without_writes(self):
        for model in ('0761', '0800', '0840'):
            cat = Cat(model)
            with patch.object(yac, '_cat_exchange', side_effect=cat.exchange), \
                 patch.object(yac, '_yaesu_vfo_side', 0), \
                 patch.object(yac, '_read_settings', return_value={'region': '1'}):
                self.assertTrue(region_plan.permits_transmission(yac, ROOT, cat.radio))
                cat.state.update({'ST': '1', 'FT': '1', 'FB': '156800000'})
                self.assertFalse(region_plan.permits_transmission(yac, ROOT, cat.radio))
                cat.state['FB'] = '007250000'
                self.assertFalse(region_plan.permits_transmission(yac, ROOT, cat.radio))
                with patch.object(yac, '_read_settings', return_value={'region': '2'}):
                    self.assertTrue(region_plan.permits_transmission(yac, ROOT, cat.radio))
                cat.state['OS0'] = '2'
                self.assertFalse(region_plan.permits_transmission(yac, ROOT, cat.radio))
            self.assertTrue(all(c[:-1] in cat.state or c in {'IF;', 'OI;'} for c in cat.commands))

    def test_icom_split_xit_and_unknown_contexts(self):
        civ = Civ()
        with patch.object(yac, '_civ_exchange', side_effect=civ.exchange), \
             patch.object(yac, '_read_settings', return_value={'region': '1'}):
            self.assertTrue(region_plan.permits_transmission(yac, ROOT, civ.radio))
            civ.state[(15, None)] = b'\x01'
            civ.state[(37, 1)] = bytes.fromhex('0000805601')  # 156.800 MHz TX
            self.assertFalse(region_plan.permits_transmission(yac, ROOT, civ.radio))
            civ.state[(15, None)] = b'\x00'
            civ.state[(33, 2)] = b'\x01'
            self.assertFalse(region_plan.permits_transmission(yac, ROOT, civ.radio))
            civ.state[(33, 2)] = b'\x00'
            del civ.state[(37, 1)]
            self.assertFalse(region_plan.permits_transmission(yac, ROOT, civ.radio))
        self.assertEqual(civ.sent, [])

    def test_rejected_guard_never_sends_native_tune_start(self):
        from types import SimpleNamespace
        radio = SimpleNamespace(radio_id_path='rad_cmds/yaesu/CAT/models/0761',
                                model_id='0761', protocol='CAT', manufacturer_key='yaesu')
        with patch('modules.verify_settings.read', return_value='001'), \
             patch('modules.verify_settings._tuner_state', return_value='0'), \
             patch.object(region_plan, 'permits_transmission', return_value=False), \
             patch('modules.verify_settings._write') as write:
            self.assertEqual(tuner_control.tune(yac, ROOT, radio, 'en'), 'Invalid')
        write.assert_not_called()

    def test_missing_plan_and_unknown_frequency_block_rf(self):
        from types import SimpleNamespace
        radio = SimpleNamespace()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(region_plan, 'transmit_frequency', return_value=14195000):
                self.assertFalse(region_plan.permits_transmission(yac, root, radio))
        with patch.object(region_plan, 'transmit_frequency', return_value=None):
            self.assertFalse(region_plan.permits_transmission(yac, ROOT, radio))

    def test_help_and_label_resources_are_aligned(self):
        for language, end in [('en', 'End of help'), ('de', 'Ende der Hilfe'),
                              ('es', 'Fin de la ayuda'), ('pl', 'Koniec pomocy')]:
            help_text = (ROOT / 'lang' / language / 'help/h034').read_text(encoding='utf-8')
            self.assertTrue(help_text.rstrip().endswith('***\n' + end + '\n***'))
            for token in ('l368',):
                label = yac._read_label(ROOT, language, token, '')
                self.assertTrue(label)
                self.assertLessEqual(len(label.replace('{value}', '').strip()), 15)
