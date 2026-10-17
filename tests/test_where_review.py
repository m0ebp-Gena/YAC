"""Repeated Where am I reads native split/duplex state without mutations."""
import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import yac
from modules import split_control, lang_sel
from modules.dummy_radio import create_dummy_radio
from tests.test_split_control import ROOT, Cat, Civ


class WhereReviewTests(unittest.TestCase):
    def test_alternation_and_any_other_key_resets_even_when_returned_from_submenu(self):
        radio=create_dummy_radio()
        keys=iter(['w','w','w','w','h','w','s','q','w','q'])
        output=io.StringIO()
        with patch.object(yac,'connect_radio',return_value=radio), \
             patch.object(yac,'_read_settings',return_value={'call':'test','lang':'en'}), \
             patch.object(lang_sel,'read_key',side_effect=lambda:next(keys)), \
             patch.object(yac,'_radio_status',return_value='Normal report') as normal, \
             patch.object(split_control,'report',return_value='Detailed report') as details,redirect_stdout(output):
            self.assertEqual(yac.main([]),0)
        self.assertEqual(details.call_count,2)
        self.assertEqual(normal.call_count,4)
        lines=output.getvalue().splitlines()
        self.assertEqual([line for line in lines if line in {'Normal report','Detailed report'}],
                         ['Normal report','Detailed report','Normal report','Detailed report','Normal report','Normal report'])

    def test_ftx_reads_live_shift_and_tone_instead_of_ini_defaults(self):
        cat=Cat(fm=True)
        cat.state.update({'OS0':'2','CT0':'1','CN00':'008'})
        before=dict(cat.state)
        with patch.object(yac,'_cat_exchange',side_effect=cat.exchange),patch.object(yac,'_yaesu_vfo_side',0):
            text=split_control.report(yac,ROOT,cat.radio,'en')
            self.assertEqual(text,'Repeater On, receive 145.6 MHz, transmit 145 MHz, CTCSS 88.5 Hz TX')
            cat.state['EX010318']='0032'
            self.assertIn('transmit 144 MHz',split_control.report(yac,ROOT,cat.radio,'en'))
        before['EX010318']='0032'
        self.assertEqual(cat.state,before)
        self.assertTrue(all(c[:-1] in cat.state or c in {'IF;','OI;'} for c in cat.commands))

    def test_yaesu_hf_uses_actual_tx_routing(self):
        cat=Cat()
        cat.state.update({'ST':'1','FT':'1','FB':'014200000'})
        with patch.object(yac,'_cat_exchange',side_effect=cat.exchange):
            self.assertEqual(split_control.report(yac,ROOT,cat.radio,'en'),
                             'Split On, receive 14.195 MHz, transmit 14.2 MHz')
            cat.state['FT']='0'
            self.assertIn('transmit 14.195 MHz',split_control.report(yac,ROOT,cat.radio,'en'))

    def test_icom_native_duplex_and_off_and_failed_read(self):
        civ=Civ(fm=True)
        civ.state.update({(15,None):b'\x11',(22,93):b'\x00'})
        with patch.object(yac,'_civ_exchange',side_effect=civ.exchange),patch.object(yac,'_civ_send',side_effect=civ.send):
            self.assertEqual(split_control.report(yac,ROOT,civ.radio,'en'),
                             'Repeater On, receive 145.6 MHz, transmit 145 MHz')
            civ.state[(15,None)]=b'\x00'
            self.assertEqual(split_control.report(yac,ROOT,civ.radio,'en'),'Split/repeater Off')
            civ.state[(15,None)]=b'\xff'
            self.assertEqual(split_control.report(yac,ROOT,civ.radio,'en'),'Split/repeater details unknown.')
        self.assertEqual(civ.sent,[])

    def test_icom_hf_and_unknown_ars(self):
        civ=Civ()
        civ.state[(15,None)]=b'\x01'
        with patch.object(yac,'_civ_exchange',side_effect=civ.exchange):
            self.assertEqual(split_control.report(yac,ROOT,civ.radio,'en'),
                             'Split On, receive 14.195 MHz, transmit 7.1 MHz')
        cat=Cat(fm=True)
        cat.state['OS0']='3'
        with patch.object(yac,'_cat_exchange',side_effect=cat.exchange):
            self.assertEqual(split_control.report(yac,ROOT,cat.radio,'en'),'Split/repeater details unknown.')

    def test_ftx_follows_radio_receive_side_after_external_selection(self):
        cat=Cat(side=1)
        cat.state.update({'ST':'1','FT':'0'})
        with patch.object(yac,'_cat_exchange',side_effect=cat.exchange),patch.object(yac,'_yaesu_vfo_side',0):
            self.assertEqual(split_control.report(yac,ROOT,cat.radio,'en'),
                             'Split On, receive 7.1 MHz, transmit 14.195 MHz')
