import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import yac
from modules import lang_sel, noise_blanker as nb
from modules.dummy_radio import create_dummy_radio
from modules.find_rad import RadioConnection
from tests.test_verify_settings import SettingsSerial

ROOT=Path(__file__).resolve().parents[1]


class NoiseBlankerTests(unittest.TestCase):
    def test_all_labels_and_placeholders_exist(self):
        import string
        fields=lambda s:{f for _,f,_,_ in string.Formatter().parse(s) if f}
        for number in range(153,160):
            english=(ROOT/f'lang/en/labels/l{number:03d}').read_text(encoding='utf-8')
            for language in ('de','es','pl'):
                text=(ROOT/f'lang/{language}/labels/l{number:03d}').read_text(encoding='utf-8')
                self.assertTrue(text.strip())
                self.assertEqual(fields(text),fields(english))
    def test_demo_toggle_navigation_off_and_limits(self):
        radio=create_dummy_radio()
        self.assertEqual(nb.operate(yac,ROOT,radio,'en',toggle=True),'Noise Blanker On')
        self.assertEqual(nb.operate(yac,ROOT,radio,'en',direction=1),'Noise Blanker Level 6')
        self.assertEqual(nb.operate(yac,ROOT,radio,'en',toggle=True),'Noise Blanker Off')
        self.assertEqual(nb.operate(yac,ROOT,radio,'en',direction=1),'Noise Blanker Off')
        self.assertEqual(radio.serial.nb_level,'006')
        self.assertEqual(nb.operate(yac,ROOT,radio,'en',toggle=True),'Noise Blanker On')
        radio.serial.nb_level='010'
        self.assertEqual(nb.operate(yac,ROOT,radio,'en',direction=1),'Noise Blanker Level 10')
        radio.serial.nb_level='000'
        self.assertEqual(nb.operate(yac,ROOT,radio,'en',direction=-1),'Noise Blanker Level 0')
        radio.serial.noise_blanker='0'  # Physical control changes are respected.
        self.assertEqual(nb.operate(yac,ROOT,radio,'en',direction=1),'Noise Blanker Off')

    def test_all_icom_frames_percentages_and_rejected_writes(self):
        for model,address in [('IC-705',0xA4),('IC-7300',0x94),('IC-7300MK2',0xB6),('IC-7600',0x7A),('IC-9700',0xA2)]:
            serial=SettingsSerial(address)
            serial.settings.update({b'\x16\x22':b'\x00',b'\x14\x12':b'\x01\x28'})
            radio=RadioConnection(serial,'test',115200,'CI-V',model,model,civ_address=address)
            with patch.object(yac,'_current_mode_code',return_value=1):
                self.assertEqual(nb.operate(yac,ROOT,radio,'en',toggle=True),'Noise Blanker On')
                self.assertEqual(serial.settings[b'\x16\x22'],b'\x01')
                self.assertEqual(nb.operate(yac,ROOT,radio,'en',direction=1),'Noise Blanker Level 51%')
                self.assertEqual(serial.settings[b'\x14\x12'],b'\x01\x31')
                serial.reject_setting=True
                self.assertEqual(nb.operate(yac,ROOT,radio,'en',toggle=True),'Noise Blanker change failed')
                serial.reject_setting=False
                serial.settings[b'\x14\x12']=b'\x0a\x00'
                self.assertEqual(nb.operate(yac,ROOT,radio,'en',direction=1),'Noise Blanker level unknown')
                serial.settings[b'\x16\x22']=b'\x02'
                before=len(serial.writes)
                self.assertEqual(nb.operate(yac,ROOT,radio,'en',toggle=True),'Noise Blanker status unknown')
                self.assertEqual(len(serial.writes),before+1)  # Status query only.

    def test_ftx_combined_state_retains_level_per_side(self):
        radio=RadioConnection(None,'test',38400,'CAT','0840','FTX-1')
        values={'0':0,'1':0}
        commands=[]
        def exchange(radio,command):
            commands.append(command)
            self.assertTrue(command.startswith('NL'))
            side=command[2]
            if len(command)>4: values[side]=int(command[3:-1])
            return f'NL{side}{values[side]:03d};'
        with patch.object(yac,'_cat_exchange',side_effect=exchange),patch.object(yac,'_current_mode_code',return_value='2'),patch.object(yac,'_yaesu_vfo_side',0):
            self.assertEqual(nb.operate(yac,ROOT,radio,'en',toggle=True),'Noise Blanker On')
            self.assertEqual(values['0'],1)
            self.assertEqual(nb.operate(yac,ROOT,radio,'en',direction=1),'Noise Blanker Level 2')
            self.assertEqual(nb.operate(yac,ROOT,radio,'en',toggle=True),'Noise Blanker Off')
            self.assertEqual(values['0'],0)
            self.assertEqual(nb.operate(yac,ROOT,radio,'en',toggle=True),'Noise Blanker On')
            self.assertEqual(values['0'],2)
        with patch.object(yac,'_cat_exchange',side_effect=exchange),patch.object(yac,'_current_mode_code',return_value='2'),patch.object(yac,'_yaesu_vfo_side',1):
            self.assertEqual(nb.operate(yac,ROOT,radio,'en',toggle=True),'Noise Blanker On')
            self.assertEqual(values['1'],1)

    def test_kenwood_formats_and_nb2_selection_retained(self):
        for model in ('023','020'):
            radio=RadioConnection(None,'test',38400,'CAT',model,model)
            if model=='020': radio._ts480_variant='1'
            values={'NB':'2' if model=='023' else '1','NL':'005'}
            def exchange(radio,command):
                prefix=command[:2]
                if command!=prefix+';': values[prefix]=command[2:-1]
                return prefix+values[prefix]+';'
            with patch.object(yac,'_current_mode_code',return_value='2'),patch.object(yac,'_cat_exchange',side_effect=exchange):
                self.assertEqual(nb.operate(yac,ROOT,radio,'en',toggle=True),'Noise Blanker Off')
                self.assertEqual(nb.operate(yac,ROOT,radio,'en',toggle=True),'Noise Blanker On')
                self.assertEqual(values['NB'],'2' if model=='023' else '1')
                self.assertEqual(nb.operate(yac,ROOT,radio,'en',direction=-1),'Noise Blanker Level 4')
                self.assertEqual(values['NL'],'004')

    def test_unsupported_modes_qmx_and_unknown_state_never_write(self):
        radio=create_dummy_radio()
        radio.serial.mode='4'
        with patch.object(yac,'_cat_exchange',wraps=yac._cat_exchange) as exchange:
            self.assertEqual(nb.operate(yac,ROOT,radio,'en',toggle=True),'Not supported')
            self.assertTrue(all(c.args[1]=='MD0;' for c in exchange.call_args_list))
        radio.serial.mode='2'
        with patch.object(yac,'_current_mode_code',return_value='2'),patch.object(yac,'_cat_exchange',return_value='?;') as exchange:
            self.assertEqual(nb.operate(yac,ROOT,radio,'en',toggle=True),'Noise Blanker status unknown')
            self.assertEqual(exchange.call_args.args[1],'NB0;')
            self.assertEqual(exchange.call_count,1)
        qmx=RadioConnection(None,'test',115200,'CAT','020','QMX Plus')
        with patch.object(yac,'_cat_exchange',return_value='?;') as exchange:
            self.assertEqual(nb.operate(yac,ROOT,qmx,'en',toggle=True),'Not supported')
            self.assertTrue(all(c.args[1]=='TY;' for c in exchange.call_args_list))

    def test_bad_level_read_and_readback_mismatch(self):
        radio=create_dummy_radio()
        with patch.object(yac,'_current_mode_code',return_value='2'),patch.object(yac,'_cat_exchange',return_value='NB00;'):
            self.assertEqual(nb.operate(yac,ROOT,radio,'en',toggle=True),'Noise Blanker change failed')
        def exchange(radio,command):
            return 'NB01;' if command=='NB0;' else '?;'
        with patch.object(yac,'_current_mode_code',return_value='2'),patch.object(yac,'_cat_exchange',side_effect=exchange):
            self.assertEqual(nb.operate(yac,ROOT,radio,'en',direction=1),'Noise Blanker level unknown')

    def test_keyboard_repeat_f_b_and_b_navigation_and_q(self):
        radio=create_dummy_radio()
        keys=iter(['f','b','.','f','b','.','b',',','q','q','q', 'y'])
        output=io.StringIO()
        with patch.object(yac,'connect_radio',return_value=radio),patch.object(yac,'_read_settings',return_value={'call':'test','lang':'en'}),patch.object(lang_sel,'read_key',side_effect=lambda:next(keys)),redirect_stdout(output):
            self.assertEqual(yac.main([]),0)
        self.assertEqual(radio.serial.nb_level,'005')
        self.assertEqual(radio.serial.noise_blanker,'1')
        self.assertIn('Noise Blanker Off',output.getvalue())
        self.assertIn('Noise Blanker Level 6',output.getvalue())


if __name__=='__main__': unittest.main()
