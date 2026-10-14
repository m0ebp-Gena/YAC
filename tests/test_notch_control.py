import io
import string
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import yac
from modules import lang_sel, notch_control as notch, verify_settings as settings
from modules.dummy_radio import create_dummy_radio
from modules.find_rad import RadioConnection
from tests.test_verify_settings import SettingsSerial

ROOT=Path(__file__).resolve().parents[1]


class NotchTests(unittest.TestCase):
    def test_demo_frequency_width_off_navigation_and_limits(self):
        radio=create_dummy_radio()
        self.assertEqual(notch.operate(yac,ROOT,radio,'en','n',toggle=True),'Manual Notch On')
        self.assertEqual(radio.serial.notch_width,'0')
        self.assertEqual(notch.operate(yac,ROOT,radio,'en','n',direction=1),'Notch Frequency 1210 hertz')
        self.assertEqual(notch.operate(yac,ROOT,radio,'en','n',width=True),'Notch Width Wide')
        self.assertEqual(radio.serial.notch_position,'121')
        self.assertEqual(notch.operate(yac,ROOT,radio,'en','n',toggle=True),'Manual Notch Off')
        self.assertEqual(notch.operate(yac,ROOT,radio,'en','n',direction=1),'Manual Notch Off')
        self.assertEqual(notch.operate(yac,ROOT,radio,'en','n',width=True),'Manual Notch Off')
        self.assertEqual(radio.serial.notch_width,'1')
        radio.serial.manual_notch='001'; radio.serial.notch_position='320'
        self.assertEqual(notch.operate(yac,ROOT,radio,'en','n',direction=1),'Notch Frequency 3200 hertz')
        radio.serial.notch_position='001'
        self.assertEqual(notch.operate(yac,ROOT,radio,'en','n',direction=-1),'Notch Frequency 10 hertz')
        self.assertEqual(notch.operate(yac,ROOT,radio,'en','a',toggle=True),'Auto Notch On')

    def test_yaesu_models_wire_formats_and_ftx_side(self):
        for model,menu in [('0761','EX030204'),('0800','EX030201'),('0840','EX030301')]:
            radio=RadioConnection(None,'test',38400,'CAT',model,model)
            side='1' if model=='0840' else '0'
            values={f'BP{side}0':'000',f'BP{side}1':'200',f'BC{side}':'0',menu:'0'}
            commands=[]
            def exchange(radio,command):
                commands.append(command)
                prefix=next(p for p in values if command.startswith(p))
                if command!=prefix+';': values[prefix]=command[len(prefix):-1]
                return prefix+values[prefix]+';'
            with patch.object(yac,'_current_mode_code',return_value='2'),patch.object(yac,'_yaesu_vfo_side',1),patch.object(yac,'_cat_exchange',side_effect=exchange):
                self.assertEqual(notch.operate(yac,ROOT,radio,'en','n',toggle=True),'Manual Notch On')
                self.assertIn(f'BP{side}0001;',commands)
                self.assertEqual(notch.operate(yac,ROOT,radio,'en','n',direction=1),'Notch Frequency 2010 hertz')
                self.assertIn(f'BP{side}1201;',commands)
                self.assertEqual(notch.operate(yac,ROOT,radio,'en','n',width=True),'Notch Width Wide')
                self.assertIn(menu+'1;',commands)

    def test_all_icom_exclusion_native_position_and_width_preserved(self):
        for model,address in [('IC-705',0xA4),('IC-7300',0x94),('IC-7300MK2',0xB6),('IC-7600',0x7A),('IC-9700',0xA2)]:
            serial=SettingsSerial(address)
            serial.settings.update({b'\x16\x41':b'\x01',b'\x16\x48':b'\x00',b'\x14\x0d':b'\x01\x28',b'\x16\x57':b'\x02'})
            radio=RadioConnection(serial,'test',115200,'CI-V',model,model,civ_address=address)
            with patch.object(yac,'_current_mode_code',return_value=1):
                self.assertEqual(notch.operate(yac,ROOT,radio,'en','n',toggle=True),'Manual Notch On')
                self.assertEqual(serial.settings[b'\x16\x41'],b'\x00')
                self.assertEqual(serial.settings[b'\x16\x48'],b'\x01')
                self.assertEqual(serial.settings[b'\x16\x57'],b'\x02')
                self.assertEqual(notch.operate(yac,ROOT,radio,'en','n',direction=1),'Notch Position 129')
                self.assertEqual(serial.settings[b'\x14\x0d'],b'\x01\x29')
                self.assertEqual(notch.operate(yac,ROOT,radio,'en','n',width=True),'Notch Width Wide')
                self.assertEqual(serial.settings[b'\x14\x0d'],b'\x01\x29')
                self.assertEqual(notch.operate(yac,ROOT,radio,'en','a',toggle=True),'Auto Notch On')
                self.assertEqual(serial.settings[b'\x16\x48'],b'\x00')

    def test_icom_failed_switch_restores_previous_filter(self):
        serial=SettingsSerial(0xA4)
        serial.settings.update({b'\x16\x41':b'\x01',b'\x16\x48':b'\x00'})
        radio=RadioConnection(serial,'test',115200,'CI-V','IC-705','IC-705',civ_address=0xA4)
        original=settings._write
        def write(yac,radio,spec,value,*args):
            return False if spec['set']=='16 48' else original(yac,radio,spec,value,*args)
        with patch.object(yac,'_current_mode_code',return_value=1),patch.object(settings,'_write',side_effect=write):
            self.assertEqual(notch.operate(yac,ROOT,radio,'en','n',toggle=True),'Notch change failed')
        self.assertEqual(serial.settings[b'\x16\x41'],b'\x01')
        self.assertEqual(serial.settings[b'\x16\x48'],b'\x00')

    def test_icom_does_not_query_inapplicable_other_filter(self):
        for mode,key,command,label in [(3,'n',b'\x16\x48','Manual Notch On'),
                                       (5,'a',b'\x16\x41','Auto Notch On')]:
            serial=SettingsSerial(0xA4)
            serial.settings[command]=b'\x00'
            radio=RadioConnection(serial,'test',115200,'CI-V','IC-705','IC-705',civ_address=0xA4)
            with patch.object(yac,'_current_mode_code',return_value=mode):
                self.assertEqual(notch.operate(yac,ROOT,radio,'en',key,toggle=True),label)
            other=b'\x16\x41' if key=='n' else b'\x16\x48'
            self.assertFalse(any(packet[4:6]==other for packet in serial.writes))

    def test_ts590_shared_modes_width_retained_and_native_position(self):
        radio=RadioConnection(None,'test',38400,'CAT','023','TS-590SG')
        values={'NT':'21','BP':'063'}
        commands=[]
        def exchange(radio,command):
            commands.append(command)
            prefix=command[:2]
            if command!=prefix+';': values[prefix]=command[2:-1]
            return prefix+values[prefix]+';'
        with patch.object(yac,'_current_mode_code',return_value='2'),patch.object(yac,'_cat_exchange',side_effect=exchange):
            self.assertEqual(notch.operate(yac,ROOT,radio,'en','n',toggle=True),'Manual Notch Off')
            self.assertEqual(notch.operate(yac,ROOT,radio,'en','a',toggle=True),'Auto Notch On')
            self.assertEqual(values['NT'],'10')
            self.assertEqual(notch.operate(yac,ROOT,radio,'en','n',toggle=True),'Manual Notch On, Notch Width Wide')
            self.assertEqual(values['NT'],'21')
            self.assertEqual(notch.operate(yac,ROOT,radio,'en','n',direction=1),'Notch Position 64')
            self.assertEqual(notch.operate(yac,ROOT,radio,'en','n',width=True),'Notch Width Normal')
            self.assertEqual(values['BP'],'064')
            self.assertFalse(any(c.startswith('BC') for c in commands))
        with patch.object(yac,'_current_mode_code',return_value='3'),patch.object(yac,'_cat_exchange',side_effect=exchange):
            self.assertEqual(notch.operate(yac,ROOT,radio,'en','a',toggle=True),'Not supported')

    def test_ts480_beat_cancel_retains_type_no_manual_and_no_position(self):
        radio=RadioConnection(None,'test',38400,'CAT','020','TS-480SAT')
        radio._ts480_variant='1'
        state=['2']; commands=[]
        def exchange(radio,command):
            commands.append(command)
            self.assertTrue(command.startswith('BC'))
            if command!='BC;': state[0]=command[2:-1]
            return 'BC'+state[0]+';'
        with patch.object(yac,'_current_mode_code',return_value='2'),patch.object(yac,'_cat_exchange',side_effect=exchange):
            self.assertEqual(notch.operate(yac,ROOT,radio,'en','a',toggle=True),'Beat Cancel Off')
            self.assertEqual(notch.operate(yac,ROOT,radio,'en','a',toggle=True),'Beat Cancel 2 On')
            before=len(commands)
            self.assertEqual(notch.operate(yac,ROOT,radio,'en','a',direction=1),'Beat Cancel 2 On')
            self.assertEqual(commands[before:],['BC;'])
            self.assertEqual(notch.operate(yac,ROOT,radio,'en','n',toggle=True),'Not supported')

    def test_unknown_reads_readback_failures_and_qmx(self):
        radio=create_dummy_radio()
        with patch.object(yac,'_current_mode_code',return_value='2'),patch.object(yac,'_cat_exchange',return_value='?;') as exchange:
            self.assertEqual(notch.operate(yac,ROOT,radio,'en','n',toggle=True),'Notch status unknown')
            self.assertEqual(exchange.call_count,1)
        with patch.object(yac,'_current_mode_code',return_value='2'),patch.object(yac,'_cat_exchange',return_value='BP00000;'):
            self.assertEqual(notch.operate(yac,ROOT,radio,'en','n',toggle=True),'Notch change failed')
        qmx=RadioConnection(None,'test',115200,'CAT','020','QMX Plus')
        with patch.object(yac,'_cat_exchange',return_value='?;') as exchange:
            self.assertEqual(notch.operate(yac,ROOT,qmx,'en','a',toggle=True),'Not supported')
            self.assertTrue(all(c.args[1]=='TY;' for c in exchange.call_args_list))

    def test_keyboard_manual_width_toggle_and_nested_q(self):
        radio=create_dummy_radio()
        keys=iter(['f','n','.','w','n','.','q','a','.','a','q','q','q'])
        output=io.StringIO()
        with patch.object(yac,'connect_radio',return_value=radio),patch.object(yac,'_read_settings',return_value={'call':'test','lang':'en'}),patch.object(lang_sel,'read_key',side_effect=lambda:next(keys)),redirect_stdout(output):
            self.assertEqual(yac.main([]),0)
        self.assertEqual(radio.serial.notch_position,'121')
        self.assertEqual(radio.serial.notch_width,'1')
        self.assertEqual(radio.serial.auto_notch,'0')
        self.assertEqual(radio.serial.manual_notch,'000')
        self.assertIn('Notch Width Wide',output.getvalue())
        self.assertIn('Manual Notch Off',output.getvalue())

    def test_translated_labels_fields(self):
        fields=lambda s:{f for _,f,_,_ in string.Formatter().parse(s) if f}
        for number in range(171,190):
            english=(ROOT/f'lang/en/labels/l{number:03d}').read_text(encoding='utf-8')
            for lang in ('de','es','pl'):
                text=(ROOT/f'lang/{lang}/labels/l{number:03d}').read_text(encoding='utf-8')
                self.assertTrue(text.strip())
                self.assertEqual(fields(text),fields(english))


if __name__=='__main__': unittest.main()
