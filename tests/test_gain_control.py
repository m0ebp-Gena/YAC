from pathlib import Path
from unittest.mock import patch
import unittest
import yac
from modules import gain_control as gain, lang_sel
from modules.dummy_radio import create_dummy_radio
from modules.find_rad import RadioConnection
from tests.test_verify_settings import SettingsSerial
ROOT=Path(__file__).resolve().parents[1]

class GainTests(unittest.TestCase):
    def test_live_demo_limits_and_mode(self):
        r=create_dummy_radio()
        self.assertEqual(gain.adjust(yac,ROOT,r,'en','a'),'AF Gain 50%')
        self.assertEqual(r.serial.gains['AG0'],128)
        self.assertEqual(gain.adjust(yac,ROOT,r,'en','a',1),'AF Gain 53%')
        r.serial.gains['AG0']=1
        self.assertEqual(gain.adjust(yac,ROOT,r,'en','a',-1),'AF Gain 0%')
        self.assertEqual(gain.adjust(yac,ROOT,r,'en','r',1),'RF Gain 100%')
        r.serial.mode='4'
        self.assertEqual(gain.adjust(yac,ROOT,r,'en','r',1),'Squelch 3%')
        self.assertEqual(r.serial.gains['RG0'],255)

    def test_every_icom_bcd_ack_and_bad_data(self):
        for model,address in [('IC-705',0xA4),('IC-7300',0x94),('IC-7300MK2',0xB6),('IC-7600',0x7A),('IC-9700',0xA2)]:
            with self.subTest(model=model):
                serial=SettingsSerial(address)
                serial.settings.update({b'\x14\x01':b'\x01\x28',b'\x14\x02':b'\x02\x55',b'\x14\x03':b'\x00\x00'})
                r=RadioConnection(serial,'test',115200,'CI-V',model,model,civ_address=address)
                self.assertEqual(gain.adjust(yac,ROOT,r,'en','a',1),'AF Gain 53%')
                self.assertEqual(serial.settings[b'\x14\x01'],b'\x01\x36')
                with patch.object(yac,'_current_mode_code',return_value=5):
                    self.assertEqual(gain.adjust(yac,ROOT,r,'en','r',1),'Squelch 3%')
                serial.reject_setting=True
                self.assertEqual(gain.adjust(yac,ROOT,r,'en','a',1),'Setting change failed')
                serial.settings[b'\x14\x01']=b'\x0a\x00'
                self.assertEqual(gain.adjust(yac,ROOT,r,'en','a',1),'Gain unknown')

    def test_cat_models_wire_formats_and_selected_side(self):
        for model,prefix,maxsql in [('0761','0',100),('0800','0',100),('0840','1',255),('023','0',255)]:
            r=RadioConnection(None,'test',38400,'CAT',model,model)
            values={'AG':128,'RG':128,'SQ':0}
            commands=[]
            def exchange(radio,cmd):
                commands.append(cmd)
                control=cmd[:2]
                side='' if model=='023' and control=='RG' else prefix
                base=control+side
                self.assertTrue(cmd.startswith(base))
                payload=cmd[len(base):-1]
                if payload: values[control]=int(payload)
                return f'{base}{values[control]:03d};'
            with patch.object(yac,'_cat_exchange',side_effect=exchange),patch.object(yac,'_current_mode_code',return_value='4'),patch.object(yac,'_yaesu_vfo_side',1):
                self.assertEqual(gain.adjust(yac,ROOT,r,'en','a',1),'AF Gain 53%')
                self.assertEqual(gain.adjust(yac,ROOT,r,'en','r',1),'Squelch 3%')
                self.assertEqual(values['SQ'],3 if maxsql==100 else 8)
                with patch.object(yac,'_current_mode_code',return_value='2'):
                    self.assertEqual(gain.adjust(yac,ROOT,r,'en','r',-1),'RF Gain 47%')
                with patch.object(yac,'_current_mode_code',return_value=None):
                    before=len(commands)
                    self.assertEqual(gain.adjust(yac,ROOT,r,'en','r',1),'Gain unknown')
                    self.assertEqual(len(commands),before)

    def test_keyboard_exits_and_forwards(self):
        import io
        from contextlib import redirect_stdout
        r=create_dummy_radio()
        keys=iter(['a','.','q','r',',','w','q'])
        with patch.object(yac,'connect_radio',return_value=r),patch.object(yac,'_read_settings',return_value={'call':'test','lang':'en'}),patch.object(lang_sel,'read_key',side_effect=lambda:next(keys)),redirect_stdout(io.StringIO()):
            self.assertEqual(yac.main([]),0)
        self.assertEqual(r.serial.gains['AG0'],136)
        self.assertEqual(r.serial.gains['RG0'],247)
