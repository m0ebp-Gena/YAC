"""Regressions from real AC100 / rejected AC001 and hardware CAT errata."""
import unittest
from unittest.mock import patch
from pathlib import Path

import yac
from modules import verify_settings, tuner_control
from modules.dummy_radio import create_dummy_radio

ROOT = Path(__file__).resolve().parents[1]


class FTX:
    def __init__(self):
        self.values={'030104':'0','030701':'0','030702':'2','030703':'0','030704':'0'}
        self.ac='100'  # Actual user's log, not the old synthetic AC000.
        self.power='2'
        self.commands=[]
        self.reject=None
        self.tune_reads=0

    def exchange(self, radio, command):
        if command in ('AC103;AC;', 'AC123;AC;'):
            if command == self.reject:
                self.commands.append(command)
                return '?;'
            return self.exchange(radio, command[:6]) + self.exchange(radio, 'AC;')
        self.commands.append(command)
        if command == self.reject: return '?;'
        if command == 'PC;': return f'PC{self.power}020;'
        if command == 'FA;': return 'FA007131000;'
        if command == 'AC;':
            if self.tune_reads:
                self.tune_reads-=1
                return 'AC103;'
            return 'AC'+self.ac+';'
        if command in ('AC001;','AC003;','AC101;'):
            return '?;'  # Do not let tests repeat the old fictitious enable.
        if command in ('AC103;','AC123;'):
            self.tune_reads=1
            return ''
        if command in ('AC000;','AC120;'):
            self.ac='120' if command=='AC120;' else '100'
            return ''
        if command.startswith('EX'):
            number=command[2:8]
            if number not in self.values:return '?;'
            if len(command)>9:self.values[number]=command[8:-1];return ''
            return 'EX'+number+self.values[number]+';'
        return '?;'


class FTXTunerTests(unittest.TestCase):
    def setUp(self):
        # Keep hardware-errata tests focused on the native tuner sequence;
        # actual regional TX-frequency checks have separate transport tests.
        guard = patch('modules.region_plan.permits_transmission', return_value=True)
        guard.start(); self.addCleanup(guard.stop)
        self.radio=create_dummy_radio();self.radio.model_id='0840'
        self.ftx=FTX()
        self.patch=patch.object(yac,'_cat_exchange',side_effect=self.ftx.exchange)
        self.patch.start();self.addCleanup(self.patch.stop)

    def cycle(self):
        return verify_settings.cycle(yac,ROOT,self.radio,'en','tuner')

    def test_actual_idle_reply_does_not_mean_tuner_off(self):
        text=verify_settings.verify(yac,ROOT,self.radio,'en')
        self.assertIn('tuner internal',text)
        self.assertNotIn('tuner off',text)
        self.assertTrue(all(c.endswith(';') and len(c)==9 for c in self.ftx.commands if c.startswith('EX')))
        self.assertFalse(any(c.startswith('AC') and c!='AC;' for c in self.ftx.commands))

    def test_selects_ant1_types_without_enable_or_tune(self):
        for label in ('Tuner Int Fast','tuner external','tuner ATAS','tuner internal'):
            self.assertEqual(self.cycle(),label)
        self.assertEqual(self.ftx.values['030701'],'0')
        self.assertEqual(self.ftx.values['030702'],'2')
        self.assertTrue(all(c=='AC;' for c in self.ftx.commands if c.startswith('AC')))
        self.assertNotIn('EX0301042;',self.ftx.commands)
        self.assertNotIn('EX0301043;',self.ftx.commands)

    def test_ant2_changes_only_its_tuner_type(self):
        self.ftx.values['030704']='1'
        self.assertEqual(self.cycle(),'tuner ATAS')
        self.assertEqual(self.ftx.values['030702'],'3')
        self.assertEqual(self.ftx.values['030701'],'0')

    def test_receive_only_ant2_still_uses_transmit_ant1_tuner(self):
        self.ftx.values.update({'030704':'1','030703':'2'})
        self.assertEqual(self.cycle(),'Tuner Int Fast')
        self.assertEqual(self.ftx.values['030701'],'1')
        self.assertEqual(self.ftx.values['030702'],'2')

    def test_failed_route_change_restores_previous_menu(self):
        self.ftx.values['030701']='2'
        self.ftx.reject='EX0301041;'
        self.assertEqual(self.cycle(),'Radio Error')
        self.assertEqual(self.ftx.values['030701'],'2')
        self.assertEqual(self.ftx.values['030104'],'0')

    def test_field_head_does_not_offer_internal_tuner(self):
        self.ftx.power='1'
        self.assertEqual(self.cycle(),'tuner ATAS')
        self.assertEqual(self.cycle(),'tuner external')
        self.assertFalse(any(c.startswith(('EX030701','EX030702')) for c in self.ftx.commands))

    def test_tune_internal_and_external_use_corrected_prefix(self):
        for selected in ('0','1','2'):
            self.ftx.values['030701']=selected
            with patch('modules.ftx_tuner.time.sleep'),patch('builtins.print'):
                self.assertEqual(tuner_control.tune(yac,ROOT,self.radio,'en'),'Tune Finished')
        self.assertEqual(self.ftx.commands.count('AC103;'),3)
        self.assertNotIn('AC003;',self.ftx.commands)

    def test_atas_uses_its_own_start(self):
        self.ftx.values.update({'030104':'1','030701':'3'})
        with patch('modules.ftx_tuner.time.sleep'),patch('builtins.print'):
            self.assertEqual(tuner_control.tune(yac,ROOT,self.radio,'en'),'Tune Finished')
        self.assertIn('AC123;',self.ftx.commands)

    def test_completed_tune_returns_on_ac101_without_bypass(self):
        self.ftx.ac='101'
        with patch('modules.ftx_tuner.time.sleep'),patch('builtins.print'):
            self.assertEqual(tuner_control.tune(yac,ROOT,self.radio,'en'),'Tune Finished')
        self.assertIn('AC103;',self.ftx.commands)
        self.assertNotIn('AC000;',self.ftx.commands)

    def test_on_state_does_not_block_selection(self):
        self.ftx.ac='101'
        self.assertEqual(self.cycle(),'Tuner Int Fast')

    def test_busy_and_unknown_never_write(self):
        self.ftx.ac='103'
        self.assertEqual(self.cycle(),'tuner tuning')
        self.ftx.ac='100';self.ftx.reject='EX030704;'
        self.assertEqual(self.cycle(),'tuner unknown')
        self.assertFalse(any(c.startswith('EX') and len(c)>9 for c in self.ftx.commands))

    def test_timeout_requests_native_stop(self):
        self.ftx.tune_reads=0
        def exchange(radio,command):
            if command=='AC103;AC;':
                self.ftx.ac='103';self.ftx.commands.append('AC103;');return 'AC103;'
            return self.ftx.exchange(radio,command)
        with patch.object(yac,'_cat_exchange',side_effect=exchange), \
             patch('modules.ftx_tuner.time.sleep'),patch('builtins.print'):
            self.assertIn('Tune Timed Out',tuner_control.tune(yac,ROOT,self.radio,'en',polls=2))
        self.assertIn('AC000;',self.ftx.commands)

    def test_initial_busy_reply_is_read_before_first_sleep(self):
        events=[]
        def exchange(radio,command):
            events.append(command)
            return self.ftx.exchange(radio,command)
        with patch.object(yac,'_cat_exchange',side_effect=exchange), \
             patch('modules.ftx_tuner.time.sleep',side_effect=lambda _:events.append('sleep')), \
             patch('builtins.print'):
            self.assertEqual(tuner_control.tune(yac,ROOT,self.radio,'en'),'Tune Finished')
        start=events.index('AC103;AC;')
        self.assertEqual(events[start:],['AC103;AC;','sleep','AC;'])

    def test_rejected_compound_start_does_not_claim_completion(self):
        self.ftx.reject='AC103;AC;'
        with patch('modules.ftx_tuner.time.sleep'),patch('builtins.print'):
            self.assertEqual(tuner_control.tune(yac,ROOT,self.radio,'en'),'Tune Failed')

    def test_missing_initial_reply_requests_stop(self):
        def exchange(radio,command):
            if command=='AC103;AC;':
                self.ftx.ac='103'
                return ''
            return self.ftx.exchange(radio,command)
        with patch.object(yac,'_cat_exchange',side_effect=exchange), \
             patch('modules.ftx_tuner.time.sleep'),patch('builtins.print'):
            self.assertIn('Tune Timed Out',tuner_control.tune(yac,ROOT,self.radio,'en'))
        self.assertIn('AC000;',self.ftx.commands)
