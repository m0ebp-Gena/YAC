"""Native antenna routing, preservation of unrelated fields and menu access."""
import io
import string
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import yac
from modules import antenna_control as ant, lang_sel
from modules.find_rad import RadioConnection
from modules.dummy_radio import create_dummy_radio

ROOT=Path(__file__).resolve().parents[1]


class AntennaTests(unittest.TestCase):
    def cat(self,model):
        return RadioConnection(None,'test',38400,'CAT',model,model)

    def test_ts590_preserves_receive_and_drive_output_fields(self):
        radio=self.cat('023')
        state=['011']
        commands=[]
        def exchange(r,c):
            commands.append(c)
            if c != 'AN;':
                self.assertRegex(c,r'^AN[019]{3};$')
                state[0]=''.join(old if new == '9' else new for old,new in zip(state[0],c[2:-1]))
            return 'AN'+state[0]+';'
        with patch.object(yac,'_cat_exchange',side_effect=exchange):
            self.assertEqual(ant.operate(yac,ROOT,radio,'en'),'Transmit antenna 1, receive antenna RX input')
            self.assertIn('Transmit antenna 2',ant.operate(yac,ROOT,radio,'en','x'))
            self.assertEqual(state[0],'111')
            self.assertIn('receive antenna 2',ant.operate(yac,ROOT,radio,'en','r'))
        self.assertEqual(state[0],'101')
        self.assertIn('AN199;',commands)
        self.assertIn('AN909;',commands)

    def test_ts480_identity_gate_and_its_different_antenna_numbers(self):
        radio=self.cat('020')
        state=['1']
        def exchange(r,c):
            if c != 'AN;': state[0]=c[2]
            return 'AN'+state[0]+';'
        with patch.object(ant.ts480_control,'variant',return_value='1'),patch.object(yac,'_cat_exchange',side_effect=exchange):
            self.assertIn('Transmit antenna 2',ant.operate(yac,ROOT,radio,'en','x'))
            self.assertEqual(ant.operate(yac,ROOT,radio,'en','r'),'Not supported')
        with patch.object(ant.ts480_control,'variant',return_value=None),patch.object(yac,'_cat_exchange') as cat:
            self.assertEqual(ant.operate(yac,ROOT,radio,'en','x'),'Not supported')
            cat.assert_not_called()

    def test_icom_main_and_rx_are_independent_with_readback(self):
        for model in ('IC-7600','IC-7300MK2'):
            radio=RadioConnection(None,'test',115200,'CI-V',model,model,civ_address=122)
            state=[b'\x00\x01']
            sent=[]
            def read(r,c,s=None): return bytes([254,254,224,122,18])+state[0]+b'\xfd'
            def write(r,c,data):
                sent.append((c,data))
                state[0]=data
                return bytes([254,254,224,122,251,253])
            with patch.object(yac,'_civ_exchange',side_effect=read),patch.object(yac,'_civ_send',side_effect=write):
                result=ant.operate(yac,ROOT,radio,'en','x')
                if model == 'IC-7600':
                    self.assertIn('Transmit antenna 2',result)
                    self.assertEqual(state[0],b'\x01\x01')
                else:
                    self.assertEqual(result,'Not supported')
                    self.assertEqual(sent,[])
                ant.operate(yac,ROOT,radio,'en','r')
                self.assertEqual(state[0][1],0)

    def ftx(self,action,selected='0',operation='0',reject=None,power='PC2020;',frequency='14.2'):
        state={'EX030704':selected,'EX030703':operation}
        commands=[]
        history=[]
        def exchange(r,c):
            commands.append(c)
            if c == 'PC;': return power
            if c == reject: return '?;'
            for key in state:
                if c == key+';': return key+state[key]+';'
                if c.startswith(key):
                    state[key]=c[-2]
                    history.append(dict(state))
                    return ''
            return '?;'
        with patch.object(yac,'_current_frequency',return_value=frequency),patch.object(yac,'_cat_exchange',side_effect=exchange):
            output=ant.operate(yac,ROOT,self.cat('0840'),'en',action)
        return output,state,commands,history

    def test_ftx_receive_toggle_never_promotes_rx_only_port_to_tx(self):
        output,state,commands,history=self.ftx('r')
        self.assertEqual(output,'Transmit antenna 1, receive antenna 2')
        self.assertEqual(state,{'EX030704':'1','EX030703':'2'})
        output,state,commands,history=self.ftx('r','1','2')
        self.assertEqual(output,'Transmit antenna 1, receive antenna 1')
        for item in history:
            self.assertFalse(item['EX030703']=='0' and item['EX030704']=='1')
        for operation in ('1','2'):
            output,_,commands,_=self.ftx('x','1',operation)
            self.assertEqual(output,'Not supported')
            self.assertTrue(all(c in {'PC;','EX030703;','EX030704;'} for c in commands))
        self.assertIn('Select transmit antenna 1',self.ftx('r','1','0')[0])

    def test_ftx_main_cycle_gates_and_failed_partial_change_reports_live_state(self):
        self.assertEqual(self.ftx('x')[0],'Transmit antenna 2, receive antenna 2')
        for kwargs in ({'power':'PC1005;'}, {'frequency':'145.5'}):
            output,_,commands,_=self.ftx('x',**kwargs)
            self.assertEqual(output,'Antenna routing unknown.')
            self.assertTrue(all(c in {'PC;','EX030703;','EX030704;'} for c in commands))
        output,state,_,_=self.ftx('r',reject='EX0307041;')
        self.assertIn('Antenna change failed.',output)
        self.assertIn('Transmit antenna 1, receive antenna 1',output)

    def test_unknown_and_rejected_reads_never_become_off_or_change(self):
        radio=self.cat('023')
        with patch.object(yac,'_cat_exchange',return_value='?;') as exchange:
            self.assertEqual(ant.operate(yac,ROOT,radio,'en','x'),'Antenna routing unknown.')
            self.assertEqual([c.args[1] for c in exchange.call_args_list],['AN;'])
        with patch.object(yac,'_cat_exchange',return_value='AN001;') as exchange:
            self.assertIn('Antenna change failed.',ant.operate(yac,ROOT,radio,'en','x'))
            self.assertIn('AN199;',[c.args[1] for c in exchange.call_args_list])

    def test_single_antenna_and_unsupported_radio_no_commands(self):
        for model in ('0761','0800','0840'):
            if model=='0840': continue
            with patch.object(yac,'_cat_exchange') as exchange:
                self.assertEqual(ant.operate(yac,ROOT,self.cat(model),'en'),'Transmit antenna 1, receive antenna 1')
                self.assertEqual(ant.operate(yac,ROOT,self.cat(model),'en','x'),'Not supported')
                exchange.assert_not_called()
        radio=RadioConnection(None,'test',115200,'CI-V','IC-9700','IC-9700',civ_address=162)
        self.assertEqual(ant.operate(yac,ROOT,radio,'en'),'Not supported')

    def test_menu_entry_help_back_and_command_passthrough(self):
        keys=iter(['h','q'])
        radio=create_dummy_radio()
        output=io.StringIO()
        with redirect_stdout(output):
            self.assertIsNone(ant.control(yac,ROOT,radio,'en',lambda:next(keys),SimpleNamespace(lost=False)))
        self.assertIn('Antennas:',output.getvalue())
        self.assertTrue(output.getvalue().endswith('Back'))
        self.assertEqual(ant.control(yac,ROOT,radio,'en',lambda:'w',SimpleNamespace(lost=False)),'w')

    def test_top_level_x_dispatch_and_localized_help_and_fields(self):
        keys=iter(['x','q'])
        with patch.object(yac,'connect_radio',return_value=create_dummy_radio()), \
             patch.object(yac,'_read_settings',return_value={'call':'test','lang':'en'}), \
             patch.object(lang_sel,'read_key',side_effect=lambda:next(keys)), \
             patch.object(ant,'control',return_value=None) as control,redirect_stdout(io.StringIO()):
            self.assertEqual(yac.main([]),0)
        control.assert_called_once()
        fields=lambda text:{f for _,f,_,_ in string.Formatter().parse(text) if f}
        for number in range(260,265):
            english=(ROOT/f'lang/en/labels/l{number}').read_text(encoding='utf-8')
            for language in ('de','pl','es'):
                self.assertEqual(fields(english),fields((ROOT/f'lang/{language}/labels/l{number}').read_text(encoding='utf-8')))
                self.assertTrue((ROOT/f'lang/{language}/help/h012').read_text(encoding='utf-8').strip())
