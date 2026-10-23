"""Protocol-aware split and repeater regression checks without RF transmission."""
import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import yac
from modules import split_control as split, lang_sel
from modules.find_rad import RadioConnection
from modules.dummy_radio import create_dummy_radio

ROOT = Path(__file__).resolve().parents[1]


class Cat:
    def __init__(self, model='0840', side=0, fm=False):
        self.radio = RadioConnection(None, 'test', 38400, 'CAT', model, model)
        self.state = {'VS': str(side), 'ST':'0', 'FT':str(side),
                      'FA':'145600000' if fm else '014195000', 'FB':'007100000',
                      'MD0':'4' if fm else '2', 'MD1':'1', 'OS0':'0', 'OS1':'0',
                      'EX010318':'0012', 'EX010319':'0152', 'EX010316':'0100'}
        self.commands = []
        self.reject = None

    def exchange(self, radio, command):
        self.commands.append(command)
        if command == self.reject:
            return '?;'
        body = command[:-1]
        if body in {'IF','OI'}:
            side = 0 if body == 'IF' else 1
            digits = 5 if radio.model_id == '0840' else 3
            return body + '0'*digits + self.state['FA' if side == 0 else 'FB'] + '+000000' + self.state['MD'+str(side)] + '00000;'
        if body in self.state:
            return body + self.state[body] + ';'
        for key in sorted(self.state, key=len, reverse=True):
            if body.startswith(key):
                value = body[len(key):]
                if key == 'FT' and radio.model_id == '0761':
                    value = str(int(value) - 2)
                self.state[key] = value
                return ''
        return '?;'


class Civ:
    def __init__(self, fm=False):
        self.radio = RadioConnection(None, 'test', 115200, 'CI-V', 'IC-705', 'IC-705', civ_address=164)
        encode = lambda hz: bytes.fromhex(f'{hz:010d}')[::-1]
        self.state = {(15,None):b'\x00', (37,0):encode(145600000 if fm else 14195000),
                      (37,1):encode(7100000), (38,0):bytes([5 if fm else 1,0,2]),
                      (38,1):bytes([0,1,3]), (12,None):b'\x00\x60\x00',
                      (33,1):b'\x00', (33,2):b'\x00'}
        self.sent = []
        self.reject = None

    def exchange(self, radio, command, sub=None):
        data = self.state.get((command,sub))
        if data is None:
            return bytes.fromhex('FEFEE0A4FAFD')
        return bytes([254,254,224,164,command]) + (bytes([sub]) if sub is not None else b'') + data + b'\xfd'

    def send(self, radio, command, payload):
        self.sent.append((command,payload))
        if (command,payload) == self.reject:
            return bytes.fromhex('FEFEE0A4FAFD')
        sub = payload[0] if command in {37,38} else None
        data = payload[1:] if sub is not None else payload
        self.state[(12 if command == 13 else command,sub)] = data
        return bytes.fromhex('FEFEE0A4FBFD')


class SplitTests(unittest.TestCase):
    def test_yaesu_hf_both_receive_sides_and_ft_set_encoding(self):
        for model in ('0761','0800','0840'):
            for side in (0,1):
                cat = Cat(model, side)
                with self.subTest(model=model,side=side), patch.object(yac,'_cat_exchange',side_effect=cat.exchange), \
                     patch.object(yac,'_yaesu_vfo_side',side):
                    backend = split.Radio(yac,ROOT,cat.radio).prepare()
                    rx = backend.rx
                    ok, tx = backend.enable(14200000)
                    self.assertTrue(ok)
                    self.assertEqual(backend.frequency('rx'),rx)
                    self.assertEqual(backend.frequency('tx'),tx)
                    self.assertEqual(cat.state['ST'],'1')
                    self.assertEqual(cat.state['MD'+str(1-side)],cat.state['MD'+str(side)])
                    self.assertTrue(backend.prepare().off())
                    self.assertEqual(cat.state['ST'],'0')
                    self.assertFalse(any(c.startswith(('TX','AB','SV','FR')) for c in cat.commands))

    def test_yaesu_rejected_enable_restores_other_vfo_and_mode(self):
        cat = Cat()
        before = dict(cat.state)
        cat.reject = 'ST1;'
        with patch.object(yac,'_cat_exchange',side_effect=cat.exchange), patch.object(yac,'_yaesu_vfo_side',0):
            backend = split.Radio(yac,ROOT,cat.radio).prepare()
            self.assertFalse(backend.enable(14200000)[0])
            self.assertTrue(backend.restored)
        self.assertEqual(cat.state,before)

    def test_ftx_repeater_uses_50khz_units_and_keeps_tone_and_vfos(self):
        cat = Cat(fm=True)
        before = dict(cat.state)
        with patch.object(yac,'_cat_exchange',side_effect=cat.exchange), patch.object(yac,'_yaesu_vfo_side',0):
            backend = split.Radio(yac,ROOT,cat.radio).prepare()
            self.assertEqual(backend.enable(-600000),(True,145000000))
            self.assertEqual(cat.state['EX010318'],'0012')
            self.assertEqual(cat.state['OS0'],'2')
            self.assertTrue(backend.prepare().off())
        for key in ('FA','FB','MD0','MD1','FT'):
            self.assertEqual(cat.state[key],before[key])
        self.assertFalse(any(c.startswith(('CN','CT')) for c in cat.commands))

    def test_bad_value_or_changed_rx_never_writes(self):
        for target in (0,145700001,999999999):
            cat = Cat(fm=True)
            with patch.object(yac,'_cat_exchange',side_effect=cat.exchange), patch.object(yac,'_yaesu_vfo_side',0):
                backend = split.Radio(yac,ROOT,cat.radio).prepare()
                with self.assertRaises(ValueError):
                    backend.enable(target)
            self.assertTrue(all(c[:-1] in cat.state or c in {'IF;', 'OI;'} for c in cat.commands))
        cat = Cat()
        with patch.object(yac,'_cat_exchange',side_effect=cat.exchange), patch.object(yac,'_yaesu_vfo_side',0):
            backend = split.Radio(yac,ROOT,cat.radio).prepare()
            cat.state['FA']='014196000'
            with self.assertRaises(split.Unavailable):
                backend.enable(14200000)
            self.assertEqual(cat.state['ST'],'0')

    def test_civ_hf_preserves_rx_and_copies_full_mode_data_filter(self):
        civ = Civ()
        with patch.object(yac,'_civ_exchange',side_effect=civ.exchange), patch.object(yac,'_civ_send',side_effect=civ.send):
            backend = split.Radio(yac,ROOT,civ.radio).prepare()
            self.assertEqual(backend.enable(14200000),(True,14200000))
            self.assertEqual(backend.frequency('rx'),14195000)
            self.assertEqual(civ.state[(38,1)],civ.state[(38,0)])
            self.assertTrue(backend.prepare().off())
        self.assertFalse(any(command in {7,28} for command,_ in civ.sent))

    def test_civ_fm_native_duplex_and_rejected_command_rollback(self):
        for rejected in (False,True):
            civ = Civ(fm=True)
            before = dict(civ.state)
            if rejected:
                civ.reject = (15,b'\x11')
            with patch.object(yac,'_civ_exchange',side_effect=civ.exchange), patch.object(yac,'_civ_send',side_effect=civ.send):
                backend = split.Radio(yac,ROOT,civ.radio).prepare()
                self.assertEqual(backend.enable(-600000)[0],not rejected)
                if rejected:
                    self.assertEqual(civ.state,before)
                    self.assertTrue(backend.restored)
                else:
                    self.assertEqual(civ.state[(15,None)],b'\x11')
                    self.assertEqual(civ.state[(12,None)],b'\x00\x60\x00')
                    self.assertTrue(backend.prepare().off())
            self.assertFalse(any(command in {7,37,38,27,28} for command,_ in civ.sent))

    def test_restricted_or_unreadable_context_has_no_setters(self):
        civ = Civ()
        civ.state[(38,0)] = b'\x01'  # malformed mode response
        with patch.object(yac,'_civ_exchange',side_effect=civ.exchange), patch.object(yac,'_civ_send',side_effect=civ.send):
            with self.assertRaises(split.Unavailable):
                split.Radio(yac,ROOT,civ.radio).prepare()
        self.assertEqual(civ.sent,[])
        for model in ('020','023'):
            radio=RadioConnection(None,'test',38400,'CAT',model,model)
            with self.assertRaises(split.Unavailable):
                split.Radio(yac,ROOT,radio)

    def test_cancel_help_ini_default_and_live_toggle(self):
        for entered in ('','q'):
            civ=Civ()
            output=io.StringIO()
            with patch.object(yac,'_civ_exchange',side_effect=civ.exchange), patch.object(yac,'_civ_send',side_effect=civ.send), \
                 patch('builtins.input',return_value=entered), redirect_stdout(output):
                split.control(yac,ROOT,civ.radio,'en')
            self.assertIn('Done',output.getvalue())
            self.assertEqual(civ.sent,[])
        civ=Civ(fm=True)
        output=io.StringIO()
        with patch.object(yac,'_civ_exchange',side_effect=civ.exchange), patch.object(yac,'_civ_send',side_effect=civ.send), \
             patch.object(yac,'_read_settings',return_value={'repeater_offset_2m_hz':'-600000'}), \
             patch('builtins.input',side_effect=AssertionError('Default must not prompt')), redirect_stdout(output):
            split.control(yac,ROOT,civ.radio,'en')
            split.control(yac,ROOT,civ.radio,'en')
        self.assertIn('Repeater On, receive 145.6 MHz, transmit 145 MHz',output.getvalue())
        self.assertIn('Off',output.getvalue())

    def test_top_level_l_dispatch(self):
        radio=create_dummy_radio()
        keys=iter(['l','q', 'y'])
        with patch.object(yac,'connect_radio',return_value=radio), \
             patch.object(yac,'_read_settings',return_value={'call':'test','lang':'en'}), \
             patch.object(lang_sel,'read_key',side_effect=lambda:next(keys)), \
             patch.object(split,'control') as control, redirect_stdout(io.StringIO()):
            self.assertEqual(yac.main([]),0)
        control.assert_called_once()

    def test_parse_and_format(self):
        self.assertEqual(split.parse('14.200',False),14200000)
        self.assertEqual(split.parse('-600000',True),-600000)
        self.assertEqual(split.mhz(14195000),'14.195')
        for value in ('nan','inf','1e3','-14.2','14.1234567','0'):
            with self.assertRaises(ValueError): split.parse(value,False)

    def test_memory_mode_and_clarifier_block_enable_without_setters(self):
        cat = Cat()
        original = cat.exchange
        def memory(radio,command):
            if command == 'IF;':
                return 'IF000014195000+000000210000;'
            return original(radio,command)
        with patch.object(yac,'_cat_exchange',side_effect=memory), patch.object(yac,'_yaesu_vfo_side',0):
            backend=split.Radio(yac,ROOT,cat.radio).prepare()
            with self.assertRaises(split.Unavailable): backend.enable(14200000)
        self.assertEqual(cat.state['ST'],'0')
        civ=Civ()
        civ.state[(33,1)]=b'\x01'
        with patch.object(yac,'_civ_exchange',side_effect=civ.exchange),patch.object(yac,'_civ_send',side_effect=civ.send):
            backend=split.Radio(yac,ROOT,civ.radio).prepare()
            with self.assertRaises(split.Unavailable): backend.enable(14200000)
        self.assertEqual(civ.sent,[])

    def test_demo_actual_serial_and_help(self):
        radio=create_dummy_radio()
        output=io.StringIO()
        with patch('builtins.input',side_effect=['h','7.164']),redirect_stdout(output):
            split.control(yac,ROOT,radio,'en')
        self.assertIn('Split On, receive 7.159 MHz, transmit 7.164 MHz',output.getvalue())
        self.assertEqual(radio.serial.frequency,7159000)
        self.assertEqual(radio.serial.split_settings['ST'],'1')

    def test_failed_recovery_is_reported_and_leaves_split_off(self):
        cat=Cat()
        original=cat.exchange
        def exchange(radio,command):
            if command in {'ST1;','FB007100000;'}: return '?;'
            return original(radio,command)
        output=io.StringIO()
        with patch.object(yac,'_cat_exchange',side_effect=exchange),patch.object(yac,'_yaesu_vfo_side',0), \
             patch('builtins.input',return_value='14.2'),redirect_stdout(output):
            split.control(yac,ROOT,cat.radio,'en')
        self.assertIn('may not be restored',output.getvalue())
        self.assertEqual(cat.state['ST'],'0')

    def test_all_split_labels_and_help_exist_in_each_language(self):
        import string
        fields=lambda text:{name for _,name,_,_ in string.Formatter().parse(text) if name}
        for number in range(249,258):
            english=(ROOT/'lang/en/labels'/f'l{number}').read_text(encoding='utf-8')
            for language in ('de','pl','es'):
                translated=(ROOT/'lang'/language/'labels'/f'l{number}').read_text(encoding='utf-8')
                self.assertEqual(fields(english),fields(translated))
                self.assertTrue((ROOT/'lang'/language/'help/h011').exists())
