import io
import string
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import yac
from modules import lang_sel, noise_reduction as nr
from modules.dummy_radio import create_dummy_radio
from modules.find_rad import RadioConnection
from tests.test_verify_settings import SettingsSerial

ROOT=Path(__file__).resolve().parents[1]


class NoiseReductionTests(unittest.TestCase):
    def test_demo_toggles_levels_off_and_endpoints(self):
        radio=create_dummy_radio()
        self.assertEqual(nr.operate(yac,ROOT,radio,'en',toggle=True),'NR On')
        self.assertEqual(nr.operate(yac,ROOT,radio,'en',direction=1),'NR Level 6')
        self.assertEqual(nr.operate(yac,ROOT,radio,'en',toggle=True),'NR Off')
        self.assertEqual(nr.operate(yac,ROOT,radio,'en',direction=1),'NR Off')
        self.assertEqual(radio.serial.nr_level,'06')
        radio.serial.noise_reduction='1'; radio.serial.nr_level='15'
        self.assertEqual(nr.operate(yac,ROOT,radio,'en',direction=1),'NR Level 15')
        radio.serial.nr_level='01'
        self.assertEqual(nr.operate(yac,ROOT,radio,'en',direction=-1),'NR Level 1')

    def test_all_icom_wire_formats_percent_and_failures(self):
        for model,address in [('IC-705',0xA4),('IC-7300',0x94),('IC-7300MK2',0xB6),('IC-7600',0x7A),('IC-9700',0xA2)]:
            serial=SettingsSerial(address)
            serial.settings.update({b'\x16\x40':b'\x00',b'\x14\x06':b'\x01\x28'})
            radio=RadioConnection(serial,'test',115200,'CI-V',model,model,civ_address=address)
            with patch.object(yac,'_current_mode_code',return_value=1):
                self.assertEqual(nr.operate(yac,ROOT,radio,'en',toggle=True),'NR On')
                self.assertEqual(serial.settings[b'\x16\x40'],b'\x01')
                self.assertEqual(nr.operate(yac,ROOT,radio,'en',direction=1),'NR Level 51%')
                self.assertEqual(serial.settings[b'\x14\x06'],b'\x01\x31')
                serial.reject_setting=True
                self.assertEqual(nr.operate(yac,ROOT,radio,'en',direction=1),'Radio Error')
                serial.reject_setting=False
                serial.settings[b'\x14\x06']=b'\x0a\x00'
                self.assertEqual(nr.operate(yac,ROOT,radio,'en',direction=1),'Radio Error')
                serial.settings[b'\x16\x40']=b'\x02'
                before=len(serial.writes)
                self.assertEqual(nr.operate(yac,ROOT,radio,'en',toggle=True),'Radio Error')
                self.assertEqual(len(serial.writes),before+1)

    def test_ftx_combined_levels_and_main_sub_memory(self):
        radio=RadioConnection(None,'test',38400,'CAT','0840','FTX-1')
        values={'0':7,'1':0}
        def exchange(radio,command):
            self.assertTrue(command.startswith('RL'))
            side=command[2]
            if len(command)>4: values[side]=int(command[3:-1])
            return f'RL{side}{values[side]:02d};'
        with patch.object(yac,'_cat_exchange',side_effect=exchange),patch.object(yac,'_current_mode_code',return_value='2'),patch.object(yac,'_yaesu_vfo_side',0):
            self.assertEqual(nr.operate(yac,ROOT,radio,'en',toggle=True),'NR Off')
            self.assertEqual(nr.operate(yac,ROOT,radio,'en',toggle=True),'NR On')
            self.assertEqual(values['0'],7)
            self.assertEqual(nr.operate(yac,ROOT,radio,'en',direction=1),'NR Level 8')
        with patch.object(yac,'_cat_exchange',side_effect=exchange),patch.object(yac,'_current_mode_code',return_value='2'),patch.object(yac,'_yaesu_vfo_side',1):
            self.assertEqual(nr.operate(yac,ROOT,radio,'en',toggle=True),'NR On')
            self.assertEqual(values['1'],1)

    def test_kenwood_nr1_auto_nr2_time_and_retained_type(self):
        for model in ('023','020'):
            radio=RadioConnection(None,'test',38400,'CAT',model,model)
            if model=='020': radio._ts480_variant='1'
            state={'NR':'0','RL':'01'}
            commands=[]
            def exchange(radio,command):
                commands.append(command)
                prefix=command[:2]
                if command!=prefix+';': state[prefix]=command[2:-1]
                return prefix+state[prefix]+';'
            with patch.object(yac,'_current_mode_code',return_value='2'),patch.object(yac,'_cat_exchange',side_effect=exchange):
                self.assertEqual(nr.operate(yac,ROOT,radio,'en',toggle=True),'NR 1 On')
                self.assertEqual(nr.operate(yac,ROOT,radio,'en',direction=-1),
                                 'NR Auto' if model=='020' else 'NR Level 1')
                self.assertEqual(nr.operate(yac,ROOT,radio,'en',direction=1),
                                 'NR Level 1' if model=='020' else 'NR Level 2')
                state.update(NR='2',RL='00')  # Changed using the radio controls.
                self.assertEqual(nr.operate(yac,ROOT,radio,'en',direction=1),
                                 'NR Follow 4 ms')
                self.assertIn('RL01;',commands)
                state['RL']='09'
                self.assertEqual(nr.operate(yac,ROOT,radio,'en',direction=1),
                                 'NR Follow 20 ms')
                self.assertEqual(nr.operate(yac,ROOT,radio,'en',toggle=True),'NR Off')
                self.assertEqual(nr.operate(yac,ROOT,radio,'en',toggle=True),'NR 2 On')

    def test_unknown_readback_unsupported_and_no_guessing(self):
        radio=create_dummy_radio()
        with patch.object(yac,'_current_mode_code',return_value='2'),patch.object(yac,'_cat_exchange',return_value='?;') as exchange:
            self.assertEqual(nr.operate(yac,ROOT,radio,'en',toggle=True),'Radio Error')
            self.assertEqual(exchange.call_count,1)
        with patch.object(yac,'_current_mode_code',return_value='2'),patch.object(yac,'_cat_exchange',return_value='NR00;'):
            self.assertEqual(nr.operate(yac,ROOT,radio,'en',toggle=True),'Radio Error')
        qmx=RadioConnection(None,'test',115200,'CAT','020','QMX Plus')
        with patch.object(yac,'_cat_exchange',return_value='?;') as exchange:
            self.assertEqual(nr.operate(yac,ROOT,qmx,'en',toggle=True),'Not Supported')
            self.assertTrue(all(c.args[1]=='TY;' for c in exchange.call_args_list))
        radio.serial.mode='4'
        self.assertEqual(nr.operate(yac,ROOT,radio,'en',toggle=True),'Not Supported')

    def test_kenwood_fm_does_not_restore_nr2(self):
        radio=RadioConnection(None,'test',38400,'CAT','023','TS-590SG')
        radio._nr_memory={(radio.radio_id_path,'0'):'2'}
        state=['0']
        def exchange(radio,command):
            if command!='NR;':
                self.assertEqual(command,'NR1;')
                state[0]='1'
            return 'NR'+state[0]+';'
        with patch.object(yac,'_current_mode_code',return_value='4'),patch.object(yac,'_cat_exchange',side_effect=exchange):
            self.assertEqual(nr.operate(yac,ROOT,radio,'en',toggle=True),'NR 1 On')

    def test_keyboard_nested_navigation_and_repeat_toggle(self):
        radio=create_dummy_radio()
        keys=iter(['f','r','.','f','r','.','r',',','q','q','q', 'y'])
        output=io.StringIO()
        with patch.object(yac,'connect_radio',return_value=radio),patch.object(yac,'_read_settings',return_value={'call':'test','lang':'en'}),patch.object(lang_sel,'read_key',side_effect=lambda:next(keys)),redirect_stdout(output):
            self.assertEqual(yac.main([]),0)
        self.assertEqual(radio.serial.nr_level,'05')
        self.assertEqual(radio.serial.noise_reduction,'1')
        self.assertEqual(radio.serial.gains['RG0'],255)
        self.assertIn('NR Off',output.getvalue())
        self.assertIn('NR Level 6',output.getvalue())

    def test_each_q_keeps_back_visible_until_the_next_key(self):
        radio = create_dummy_radio()
        keys = iter(['f', 'r', 'q', 'q', 's', 'q', 'q', 'y'])
        output = io.StringIO()
        before_keys = []
        def read_key():
            before_keys.append(output.getvalue().splitlines()[-1] if output.getvalue() else '')
            return next(keys)
        with patch.object(yac, 'connect_radio', return_value=radio), \
             patch.object(yac, '_read_settings', return_value={'call':'test', 'lang':'en'}), \
             patch.object(lang_sel, 'read_key', side_effect=read_key), redirect_stdout(output):
            self.assertEqual(yac.main([]), 0)
        # Finishing an adjustment says Done; leaving menus says Back.
        self.assertEqual(before_keys[3], 'Done')
        for index in (4, 6):
            self.assertEqual(before_keys[index], 'Top Level')
        self.assertEqual(output.getvalue().splitlines().count('Done'), 1)
        self.assertEqual(output.getvalue().splitlines().count('Top Level'), 2)

    def test_translated_labels_have_matching_fields(self):
        fields=lambda s:{f for _,f,_,_ in string.Formatter().parse(s) if f}
        for number in (n for n in range(160,171) if n not in (163, 164, 165)):
            english=(ROOT/f'lang/en/labels/l{number:03d}').read_text(encoding='utf-8')
            for lang in ('de','es','pl'):
                text=(ROOT/f'lang/{lang}/labels/l{number:03d}').read_text(encoding='utf-8')
                self.assertTrue(text.strip())
                self.assertEqual(fields(text),fields(english))


if __name__=='__main__': unittest.main()
