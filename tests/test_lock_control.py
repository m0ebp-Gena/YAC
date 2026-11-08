"""Lock control: native state, verified changes, model capabilities and keyboard flow."""
import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import yac
from modules import lock_control as locks, lang_sel
from modules.find_rad import RadioConnection
from modules.dummy_radio import create_dummy_radio

ROOT = Path(__file__).resolve().parents[1]


class LockTests(unittest.TestCase):
    def cat(self, model):
        return RadioConnection(None, 'test', 38400, 'CAT', model, model)

    def run_control(self, radio, keys, language='en', watch=None):
        output = io.StringIO()
        with redirect_stdout(output), patch.object(locks.LOG, 'exception'):
            pending = None
            for _ in range(max(1, list(keys).count('k'))):
                pending = locks.control(yac, ROOT, radio, language,
                                        lambda: self.fail('Lock must not read another key'),
                                        watch or SimpleNamespace(lost=False))
        return output.getvalue(), pending

    def test_demo_each_press_toggles_and_returns_without_q(self):
        radio = create_dummy_radio()
        for expected, raw in [('Lock On', '1'), ('Lock Off', '0')]:
            out, pending = self.run_control(radio, [])
            self.assertEqual(out.strip(), expected)
            self.assertEqual(radio.serial.lock, raw)
            self.assertIsNone(pending)

    def test_all_yaesu_and_ts590_exact_commands_and_wrap(self):
        for model, off, on in [('0761','LK0;','LK1;'),('0800','LK0;','LK1;'),
                                ('0840','LK0;','LK1;'),('023','LK00;','LK10;')]:
            with self.subTest(model=model):
                state = ['0' if model != '023' else '00']; commands = []
                def exchange(r, command):
                    commands.append(command)
                    if command == on: state[0] = on[2:-1]
                    elif command == off: state[0] = off[2:-1]
                    elif command != 'LK;': self.fail(command)
                    return 'LK' + state[0] + ';'
                with patch.object(yac, '_cat_exchange', side_effect=exchange):
                    out, _ = self.run_control(self.cat(model), ['k','k','q'])
                self.assertIn('Lock On', out)
                self.assertEqual(state[0], off[2:-1])
                self.assertEqual([c for c in commands if c != 'LK;'], [on,off])

    def test_external_physical_lock_change_is_read_before_action(self):
        radio = create_dummy_radio()
        self.run_control(radio, [])
        radio.serial.lock = '0'
        out, _ = self.run_control(radio, [])
        self.assertEqual(out.strip(), 'Lock On')
        self.assertEqual(radio.serial.lock, '1')

    def test_ts480_identity_gate_and_both_existing_lock_bits(self):
        with patch.object(locks.ts480_control, 'variant', return_value=None), \
             patch.object(yac, '_cat_exchange') as cat:
            out, _ = self.run_control(self.cat('020'), [])
        self.assertIn('Not Supported', out)
        cat.assert_not_called()
        for initial in ('01','10','11'):
            state=[initial]
            def exchange(r,c):
                if c == 'LK00;': state[0]='00'
                elif c != 'LK;': self.fail(c)
                return 'LK'+state[0]+';'
            with patch.object(locks.ts480_control,'variant',return_value='1'), \
                 patch.object(yac,'_cat_exchange',side_effect=exchange):
                out,_=self.run_control(self.cat('020'),['k','q'])
            self.assertIn('Lock Off',out)
            self.assertEqual(state[0],'00')

    def civ(self, model, selector=None, enabled=0, scope=0, reject=None, mismatch=False):
        radio = RadioConnection(None,'test',115200,'CI-V',model,model,civ_address=0x94)
        values={bytes.fromhex('1650'):enabled}
        if selector:values[bytes.fromhex('1A05'+selector)]=scope
        writes=[]
        def frame(command, data):
            return bytes([254,254,224,148,command])+data+b'\xfd'
        def read(r,c,s):
            key=bytes([c,s]);return frame(c,key[1:]+bytes([values[key]]))
        def send(r,c,data):
            packet=bytes([c])+data
            if packet in values:
                return frame(c,data+bytes([values[packet]]))
            key=packet[:-1]
            if key not in values:self.fail('Unexpected CI-V command '+packet.hex())
            writes.append(packet)
            if reject==key:return frame(0xfa,b'')
            if not mismatch:values[key]=packet[-1]
            return frame(0xfb,b'')
        return radio,values,writes,read,send

    def test_icom_panel_models_off_dial_panel_off_exact_registers(self):
        for model,selector in [('IC-705','0063'),('IC-7300','0045'),
                                ('IC-7300MK2','0048'),('IC-9700','0059')]:
            with self.subTest(model=model):
                radio,state,writes,read,send=self.civ(model,selector,scope=1)
                with patch.object(yac,'_civ_exchange',side_effect=read), \
                     patch.object(yac,'_civ_send',side_effect=send):
                    out,_=self.run_control(radio,['k','k','k','q'])
                self.assertLess(out.index('Dial Lock'),out.index('Panel Lock'))
                self.assertLess(out.index('Panel Lock'),out.index('Lock Off'))
                t=bytes.fromhex('1A05'+selector)
                self.assertEqual(writes,[t+b'\x00',b'\x16\x50\x01',t+b'\x01',b'\x16\x50\x00'])
                self.assertEqual(state[b'\x16\x50'],0)

    def test_icom_initial_panel_cycles_off_without_changing_scope(self):
        radio,state,writes,read,send=self.civ('IC-705','0063',1,1)
        with patch.object(yac,'_civ_exchange',side_effect=read),patch.object(yac,'_civ_send',side_effect=send):
            out,_=self.run_control(radio,['q'])
        self.assertEqual(out.strip(),'Lock Off')
        self.assertEqual(writes,[bytes.fromhex('165000')])
        self.assertEqual(state[bytes.fromhex('1A050063')],1)

    def test_ic7600_has_only_off_on_and_no_menu_write(self):
        radio,state,writes,read,send=self.civ('IC-7600')
        with patch.object(yac,'_civ_exchange',side_effect=read),patch.object(yac,'_civ_send',side_effect=send):
            out,_=self.run_control(radio,['k','k','q'])
        self.assertNotIn('Panel Lock',out)
        self.assertIn('Lock On',out)
        self.assertEqual(writes,[bytes.fromhex('165001'),bytes.fromhex('165000')])

    def test_rejected_or_unconfirmed_changes_never_announce_success(self):
        for reject,mismatch in [(bytes.fromhex('1A050063'),False),(None,True),(bytes.fromhex('1650'),False)]:
            radio,state,writes,read,send=self.civ('IC-705','0063',reject=reject,mismatch=mismatch)
            with patch.object(yac,'_civ_exchange',side_effect=read),patch.object(yac,'_civ_send',side_effect=send):
                out,_=self.run_control(radio,['k','q'])
            self.assertNotIn('Dial Lock',out)
            self.assertIn('Radio Error',out)

    def test_unknown_initial_cat_or_civ_state_never_writes(self):
        for answer in ('','LK2;','junkLK0;','LK00;'):
            with patch.object(yac,'_cat_exchange',return_value=answer) as cat:
                out,_=self.run_control(self.cat('0761'),[])
            self.assertIn('Radio Error',out)
            self.assertEqual([c.args[1] for c in cat.call_args_list],['LK;'])
        radio,_,writes,_,send=self.civ('IC-705','0063')
        for answer in (b'',bytes.fromhex('fefee094165002fd'),bytes.fromhex('fefee09416500000fd')):
            with patch.object(yac,'_civ_exchange',return_value=answer),patch.object(yac,'_civ_send',side_effect=send):
                out,_=self.run_control(radio,[])
            self.assertIn('Radio Error',out)
        self.assertEqual(writes,[])

    def test_disconnect_does_not_send_lock_commands(self):
        radio=create_dummy_radio()
        with patch.object(yac,'_cat_exchange') as cat:
            out,pending=self.run_control(radio,[],watch=SimpleNamespace(lost=True))
        self.assertEqual(pending,'w')
        cat.assert_not_called()
        self.assertEqual(out,'')

    def test_real_top_level_k_returns_to_other_commands_without_q(self):
        radio=create_dummy_radio()
        keys=iter(['k','v','k','q','y'])
        output=io.StringIO()
        with patch.object(yac,'connect_radio',return_value=radio), \
             patch.object(yac,'_read_settings',return_value={'call':'test','lang':'en'}), \
             patch.object(lang_sel,'read_key',side_effect=lambda:next(keys)), \
             redirect_stdout(output):
            self.assertEqual(yac.main([]),0)
        self.assertIn('Lock On',output.getvalue())
        self.assertIn('Lock Off',output.getvalue())
        self.assertEqual(radio.serial.lock,'0')

    def test_unknown_models_and_qmx_do_not_send_lock_commands(self):
        for radio in [self.cat('unknown'),RadioConnection(None,'test',115200,'CI-V','IC-7610','IC-7610')]:
            with patch.object(yac,'_cat_exchange') as cat,patch.object(yac,'_civ_send') as civ:
                out,_=self.run_control(radio,[])
            self.assertIn('Not Supported',out);cat.assert_not_called();civ.assert_not_called()

    def test_top_level_dispatch_and_four_language_resources(self):
        keys=iter(['k','q','y'])
        with patch.object(yac,'connect_radio',return_value=create_dummy_radio()), \
             patch.object(yac,'_read_settings',return_value={'call':'test','lang':'en'}), \
             patch.object(lang_sel,'read_key',side_effect=lambda:next(keys)), \
             patch.object(locks,'control',return_value=None) as control,redirect_stdout(io.StringIO()):
            self.assertEqual(yac.main([]),0)
        control.assert_called_once()
        for lang in ('en','de','es','pl'):
            for n in range(404,408):
                text=(ROOT/f'lang/{lang}/labels/l{n}').read_text(encoding='utf-8').strip()
                self.assertTrue(text);self.assertLessEqual(len(text),15)
            help_text=(ROOT/f'lang/{lang}/help/h038').read_text(encoding='utf-8')
            self.assertTrue(help_text.strip().endswith('***'))
            for model in ('Icom','Yaesu','Kenwood','QMX','7300','705','9700','7600'):
                self.assertNotIn(model,help_text)
            if lang == 'en':
                self.assertIn('See the notes for your radio',help_text)
            self.assertIn('\nk) ',(ROOT/f'lang/{lang}/help/h001').read_text(encoding='utf-8'))
