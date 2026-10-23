"""Output-power edit validation, native frames and confirmed keyboard success."""
import io
import unittest
from pathlib import Path
from contextlib import redirect_stdout
from unittest.mock import patch
import yac
from modules import power_control as power, lang_sel
from modules.dummy_radio import create_dummy_radio
from modules.find_rad import RadioConnection
from tests.test_verify_settings import SettingsSerial
ROOT=Path(__file__).resolve().parents[1]

class PowerTests(unittest.TestCase):
    def test_demo_edit_and_invalid_values(self):
        radio=create_dummy_radio()
        spec=power.prepare(yac,ROOT,radio)
        for value in ('', '4', '101', '-1', '3.5', 'text'):
            result=power.set_value(yac,radio,spec,value)
            self.assertEqual(result,None if not value else 'l146')
            self.assertEqual(radio.serial.power,'020')
        self.assertIsNone(power.set_value(yac,radio,spec,'33'))
        self.assertEqual(radio.serial.power,'033')

    def test_ftx_preserves_active_power_unit_and_limits(self):
        radio=RadioConnection(None,'test',38400,'CAT','0840','FTX-1')
        for selector,maximum in [('1',10),('2',100)]:
            state=[f'PC{selector}005;']
            writes=[]
            def exchange(radio,command):
                if command!='PC;':
                    writes.append(command)
                    state[0]=command
                return state[0]
            with patch.object(yac,'_cat_exchange',side_effect=exchange):
                spec=power.prepare(yac,ROOT,radio)
                self.assertEqual(spec['maximum'],maximum)
                self.assertEqual(power.set_value(yac,radio,spec,str(maximum+1)),'l146')
                self.assertFalse(writes)
                self.assertIsNone(power.set_value(yac,radio,spec,str(maximum)))
                self.assertEqual(writes,[f'PC{selector}{maximum:03d};'])

    def test_ftx_prompt_reads_current_power_after_edit(self):
        radio=RadioConnection(None,'test',38400,'CAT','0840','FTX-1')
        state=['PC2010;']
        def exchange(radio,command):
            if command!='PC;':
                state[0]=command
            return state[0]
        output=io.StringIO()
        with patch.object(yac,'_cat_exchange',side_effect=exchange),patch('builtins.input',side_effect=['5','']),redirect_stdout(output):
            power.edit(yac,ROOT,radio,'en')
            power.edit(yac,ROOT,radio,'en')
        self.assertIn('power 10 watts. Power in watts (5–100)?',output.getvalue())
        self.assertIn('power 5 watts. Power in watts (5–100)?',output.getvalue())
        self.assertEqual(state[0],'PC2005;')

    def test_icom_relative_power_and_rejected_write(self):
        serial=SettingsSerial(0x94)
        radio=RadioConnection(serial,'test',115200,'CI-V','IC-7300','IC-7300',civ_address=0x94)
        spec=power.prepare(yac,ROOT,radio)
        self.assertIsNone(power.set_value(yac,radio,spec,'33'))
        self.assertEqual(serial.settings[bytes.fromhex('14 0a')],bytes.fromhex('00 84'))
        serial.reject_setting=True
        self.assertEqual(power.set_value(yac,radio,spec,'50'),'l131')

    def test_settings_power_stays_in_settings_and_confirms_success(self):
        radio=create_dummy_radio()
        keys=iter(['s','p','q','v','q', 'y'])
        output=io.StringIO()
        with patch.object(yac,'connect_radio',return_value=radio),patch.object(yac,'_read_settings',return_value={'call':'test','lang':'en'}),patch.object(lang_sel,'read_key',side_effect=lambda:next(keys)),patch('builtins.input',return_value='33'),redirect_stdout(output):
            self.assertEqual(yac.main([]),0)
        self.assertEqual(radio.serial.preamp,'0')
        self.assertEqual(radio.serial.power,'033')
        self.assertEqual(output.getvalue().count('power 33 watts'),1)
        self.assertIn('33W Set',output.getvalue())
        self.assertEqual(output.getvalue().count('Back'),1)
        self.assertIn('Bye test',output.getvalue())

    def test_705_battery_is_a_limit_not_a_rescaled_percentage(self):
        serial=SettingsSerial(0xA4)
        serial.settings[bytes.fromhex('1a 0b')]=bytes.fromhex('01')
        radio=RadioConnection(serial,'test',115200,'CI-V','IC-705','IC-705',civ_address=0xA4)
        with patch.object(yac,'_current_mode_code',return_value=1):
            spec=power.prepare(yac,ROOT,radio)
            self.assertEqual(spec['maximum'],5)
            self.assertEqual(spec['watts_at_full_scale'],10)
            self.assertIsNone(power.set_value(yac,radio,spec,'3'))
            self.assertEqual(serial.settings[bytes.fromhex('14 0a')],bytes.fromhex('00 76'))
            self.assertEqual(power.set_value(yac,radio,spec,'6'),'l146')
            serial.settings[bytes.fromhex('1a 0b')]=bytes.fromhex('00')
            self.assertEqual(power.prepare(yac,ROOT,radio)['maximum'],10)
            serial.settings[bytes.fromhex('1a 0b')]=bytes.fromhex('02')
            self.assertIsNone(power.prepare(yac,ROOT,radio))

    def test_9700_band_scales_and_am_limits(self):
        serial=SettingsSerial(0xA2)
        radio=RadioConnection(serial,'test',115200,'CI-V','IC-9700','IC-9700',civ_address=0xA2)
        for mhz,watts in [('145.500',100),('433.500',75),('1296.000',10)]:
            with patch.object(yac,'_current_frequency',return_value=mhz),patch.object(yac,'_current_mode_code',return_value=5):
                spec=power.prepare(yac,ROOT,radio)
                self.assertEqual(spec['maximum'],watts)
                self.assertIsNone(power.set_value(yac,radio,spec,str(watts)))
                self.assertEqual(serial.settings[bytes.fromhex('14 0a')],bytes.fromhex('02 55'))
        with patch.object(yac,'_current_frequency',return_value='433.500'),patch.object(yac,'_current_mode_code',return_value=2):
            self.assertEqual(power.prepare(yac,ROOT,radio)['maximum'],18.75)

    def test_help_and_invalid_edit_reprompt_without_writing(self):
        radio=create_dummy_radio()
        output=io.StringIO()
        with patch('builtins.input',side_effect=['h','999','33']),redirect_stdout(output):
            power.edit(yac,ROOT,radio,'en')
        self.assertIn('estimate, not measured output',output.getvalue())
        self.assertEqual(output.getvalue().count('Power in watts'),3)
        self.assertEqual(radio.serial.power,'033')
