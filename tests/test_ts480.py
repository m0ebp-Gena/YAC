"""TS-480 command reference checks with a stateful CAT emulator."""
import unittest
from pathlib import Path
from unittest.mock import patch

import yac
from modules import gain_control, power_control, ts480_control, verify_settings
from modules.find_rad import RadioConnection

ROOT = Path(__file__).resolve().parents[1]


class TS480:
    def __init__(self, variant='1'):
        self.variant = variant
        self.values = {'AG0':'128','RG':'100','SQ0':'000','PA':'00','RA':'0000',
                       'PC':'020','AC':'000','TN':'08','CN':'08','TO':'0','CT':'0'}
        self.vfo = '0'
        self.tx_vfo = '0'
        self.frequencies = {'0':7159000, '1':14185000}
        self.mode = '2'
        self.offset = 0
        self.rit = self.xit = self.scan = '0'
        self.commands = []

    def exchange(self, radio, command):
        self.commands.append(command)
        if command == 'TY;': return f'TY00{self.variant};'
        if command == 'FR;': return 'FR'+self.vfo+';'
        if command in {'FR0;','FR1;'}: self.vfo = command[2]; return ''
        if command == 'MD;': return 'MD'+self.mode+';'
        if command.startswith('MD'): self.mode = command[2]; return ''
        if command == 'IF;':
            return (f'IF{self.frequencies[self.vfo]:011d}     {self.offset:+05d}'
                    f'{self.rit}{self.xit}0000{self.mode}{self.vfo}{self.scan}0000 ;')
        if command == 'RC;': self.offset = 0; return ''
        if command.startswith(('RU','RD')):
            self.offset += int(command[2:-1]) * (1 if command.startswith('RU') else -1)
            return ''
        if command.startswith('RT'): self.rit = command[2]; return ''
        if command.startswith('XT'): self.xit = command[2]; return ''
        if command == 'SM0;': return 'SM00009;'
        if command in {'BU;','BD;'}:
            self.frequencies[self.vfo] = 10125000 if command == 'BU;' else 7150000
            return ''
        if command.startswith(('FA','FB')):
            side = '0' if command[1] == 'A' else '1'
            if len(command) > 3:
                self.frequencies[side] = int(command[2:-1])
                return ''
            return command[:2]+f'{self.frequencies[side]:011d};'
        for prefix in sorted(self.values, key=len, reverse=True):
            if command.startswith(prefix):
                payload = command[len(prefix):-1]
                if payload:
                    self.values[prefix] = payload + ('0' if prefix == 'PA' else '00' if prefix == 'RA' else '')
                    return ''
                return prefix+self.values[prefix]+';'
        return '?;'


class TS480Tests(unittest.TestCase):
    def radio(self):
        return RadioConnection(None,'test',38400,'CAT','020','ID020')

    def test_identification_sat_hx_and_gains(self):
        for variant, name, maximum in [('0','HX',200),('1','SAT',100),('2','50 W',50),('3','20 W',20)]:
            radio, rig = self.radio(), TS480(variant)
            with patch.object(yac,'_cat_exchange',side_effect=rig.exchange):
                config = verify_settings.catalog(ROOT, radio, yac)
                self.assertIn(name, radio.model_name)
                self.assertEqual(config['power']['maximum'], maximum)
                self.assertEqual('tuner' in config, variant == '1')
                self.assertEqual(gain_control.adjust(yac,ROOT,radio,'en','r',-1),'RF Gain 97%')
                self.assertEqual(rig.values['RG'],'097')
                self.assertEqual(gain_control.adjust(yac,ROOT,radio,'en','a',1),'AF Gain 53%')
                rig.mode='4'
                self.assertEqual(gain_control.adjust(yac,ROOT,radio,'en','r',1),'Squelch 3%')

    def test_live_power_limits_and_tuner_without_starting_tune(self):
        for variant in ('0','1'):
            radio, rig = self.radio(), TS480(variant)
            with patch.object(yac,'_cat_exchange',side_effect=rig.exchange):
                spec=power_control.prepare(yac,ROOT,radio)
                maximum=200 if variant=='0' else 100
                self.assertEqual(power_control.set_value(yac,radio,spec,str(maximum)),None)
                self.assertEqual(power_control.set_value(yac,radio,spec,str(maximum+1)),'l356')
                rig.mode='5'; rig.values['PC']='020'
                self.assertEqual(power_control.prepare(yac,ROOT,radio)['maximum'],maximum//4)
                rig.mode='2'
                self.assertEqual(verify_settings.cycle(yac,ROOT,radio,'en','preamp'),'preamp on')
                self.assertEqual(verify_settings.cycle(yac,ROOT,radio,'en','attenuator'),'ATT on')
                result=verify_settings.cycle(yac,ROOT,radio,'en','tuner')
                self.assertEqual(result,'tuner internal' if variant=='1' else 'Not Supported')
                self.assertFalse(any(c.startswith('AC') and c.endswith('1;') for c in rig.commands))
                rig.frequencies[rig.vfo]=52000000; rig.mode='2'; rig.values['PC']='020'
                self.assertEqual(power_control.prepare(yac,ROOT,radio)['maximum'],100)
                rig.mode='5'
                self.assertEqual(power_control.prepare(yac,ROOT,radio)['maximum'],25)

    def test_active_vfo_frequency_status_tuning_and_band_commands(self):
        radio, rig=self.radio(),TS480()
        with patch.object(yac,'_cat_exchange',side_effect=rig.exchange):
            self.assertEqual(yac._radio_status(ROOT,radio,'en'),'S 9 7.159 USB')
            self.assertEqual(yac._set_frequency(ROOT,radio,'en','7.2'),'7.2')
            self.assertIn('FA00007200000;',rig.commands)
            self.assertIn('VFO B',ts480_control.select_vfo(yac,ROOT,radio,'en'))
            self.assertEqual(rig.tx_vfo,'0')
            self.assertEqual(yac._set_frequency(ROOT,radio,'en','14.2'),'14.2')
            self.assertIn('FB00014200000;',rig.commands)
            self.assertEqual(rig.frequencies['0'],7200000)
            self.assertEqual(yac._step_frequency(ROOT,radio,'en',{},1),'14.201')
            rig.vfo='0'; rig.frequencies['0']=7159000
            self.assertIn('10.125',yac._band_change(ROOT,radio,'en',1))
            self.assertIn('BU;',rig.commands)
            self.assertFalse(any(c.startswith('BU') and c!='BU;' for c in rig.commands))

    def test_rit_xit_clear_and_scan_rejection(self):
        radio,rig=self.radio(),TS480()
        with patch.object(yac,'_cat_exchange',side_effect=rig.exchange):
            self.assertEqual(ts480_control.offset_state(yac,radio),(0,False,False))
            self.assertTrue(yac._zero_offsets(radio))
            self.assertEqual(yac._offset_action(ROOT,radio,'en',0,1),'Receive Plus 10 Hertz')
            self.assertEqual(yac._offset_action(ROOT,radio,'en',1,-1),'Transmit 0 Hertz')
            self.assertEqual(yac._offset_action(ROOT,radio,'en',2,1),'Clear')
            self.assertEqual((rig.offset,rig.rit,rig.xit),(0,'0','0'))
            rig.scan='1'; before=len(rig.commands)
            self.assertEqual(yac._offset_action(ROOT,radio,'en',0,1),'Radio Error')
            self.assertFalse(any(c.startswith(('RU','RD','RC','RT','XT')) for c in rig.commands[before:]))

    def test_ctcss_on_verified_ts480_only(self):
        radio,rig=self.radio(),TS480()
        with patch.object(yac,'_cat_exchange',side_effect=rig.exchange):
            self.assertEqual(yac._tone_radio_kind(radio),'ts480')
            self.assertTrue(yac._tone_band_supported('ts480','52.5'))
            self.assertFalse(yac._tone_band_supported('ts480','14.2'))
            self.assertTrue(yac._tone_command(radio,'ts480','CTCSS','88.5','TX'))
            self.assertTrue(yac._tone_command(radio,'ts480','CTCSS','88.5','Both'))
            self.assertFalse(any(c.startswith('TX') for c in rig.commands))

    def test_qmx_or_ambiguous_id_gets_no_ts480_setters(self):
        radio=self.radio()
        with patch.object(yac,'_cat_exchange',return_value='?;') as exchange:
            self.assertEqual(gain_control.adjust(yac,ROOT,radio,'en','r',1),'Not Supported')
            self.assertIsNone(power_control.prepare(yac,ROOT,radio))
            self.assertIsNone(yac._tone_radio_kind(radio))
            self.assertFalse(yac._zero_offsets(radio))
            self.assertEqual(ts480_control.select_vfo(yac,ROOT,radio,'en'),'Not Supported')
            self.assertTrue(all(c.args[1]=='TY;' for c in exchange.call_args_list))


if __name__=='__main__': unittest.main()
