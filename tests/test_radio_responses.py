"""Offline response and failure-path regression tests; no hardware access."""
import unittest,re,io
from contextlib import redirect_stdout
from unittest.mock import MagicMock
from modules import lang_sel,chat_int
from unittest.mock import patch
from pathlib import Path
import yac
from modules.find_rad import RadioConnection
root=Path(__file__).resolve().parents[1]
class Responses(unittest.TestCase):
    def radio(self,model):
        return RadioConnection(None,'mock',38400,'CI-V' if model=='IC-705' else 'CAT',model,model,civ_address=0xA4 if model=='IC-705' else None)
    def test_mode_response_consistency(self):
        for model in ['0761','0840','023','IC-705']:
            r=self.radio(model)
            for code,_ in yac._available_modes(r):
                with self.subTest(model=model,code=code):
                    expected=yac._mode_name(r,code)
                    if r.protocol=='CAT':
                        mode=f'MD0{code};' if model!='023' else f'MD{code};'
                        def exchange(r,c):
                            return mode if c.startswith('MD') else 'FA00007159000;' if c=='FA;' else 'SM00009;' if model=='023' else 'SM0130;'
                        with patch.object(yac,'_cat_exchange',side_effect=exchange):
                            self.assertEqual(yac._current_mode(r),expected)
                            self.assertTrue(yac._radio_status(root,r,'en').endswith(' '+expected))
                    else:
                        def exchange(r,c,s=None):
                            data=yac._civ_frequency_bytes(7159000) if c==3 else bytes([code,1]) if c==4 else bytes.fromhex('0120')
                            return bytes([0xFE,0xFE,0xE0,0xA4,c])+ (bytes([s]) if s is not None else b'')+data+b'\xfd'
                        with patch.object(yac,'_civ_exchange',side_effect=exchange):
                            self.assertEqual(yac._current_mode(r),expected)
                            self.assertTrue(yac._radio_status(root,r,'en').endswith(' '+expected))
    def test_rejected_frequency_restores_each_vfo(self):
        for model in ['0761','0840','023','IC-705']:
            for side in ([0,1] if model=='0840' else [0]):
                with self.subTest(model=model,side=side):
                    r=self.radio(model); sent=[]; yac._yaesu_vfo_side=side
                    with patch.object(yac,'_current_frequency',side_effect=['14.185','14.186','14.185']),patch.object(yac,'_cat_exchange',side_effect=lambda r,c:sent.append(c) or ''),patch.object(yac,'_civ_send',side_effect=lambda r,c,d:sent.append((c,d)) or bytes.fromhex('FEFEE0A4FBFD')):
                        result=yac._set_frequency(root,r,'en','14.187')
                    self.assertIn('restored',result)
                    if model=='0840': self.assertTrue(sent[-1].startswith('FB' if side else 'FA'))
        yac._yaesu_vfo_side=0
    def test_missing_frequency_prevents_write(self):
        with patch.object(yac,'_current_frequency',return_value=None),patch.object(yac,'_cat_exchange') as write:
            self.assertIn('cancelled',yac._set_frequency(root,self.radio('0840'),'en','7.159'))
            write.assert_not_called()
    def test_invalid_frequency_prevents_write(self):
        for model in ['0761','0840','023','IC-705']:
            with patch.object(yac,'_cat_exchange') as cat,patch.object(yac,'_civ_send') as civ:
                for value in ['nan','inf','-1','0','garbage','471']:
                    self.assertNotEqual(yac._set_frequency(root,self.radio(model),'en',value),value)
                cat.assert_not_called(); civ.assert_not_called()
    def test_steps_for_all_families(self):
        for mode,key,hz in [('USB','step_ssb',1000),('AM','step_am',2500),('FM','step_fm',12500),('CWU','step_cw',500)]:
            with patch.object(yac,'_current_mode',return_value=mode),patch.object(yac,'_current_frequency',return_value='7.159'),patch.object(yac,'_set_frequency',return_value='ok') as setting:
                yac._step_frequency(root,self.radio('0840'),'en',{},1)
                self.assertEqual(round(float(setting.call_args.args[3])*1e6),7159000+hz)
    def test_yaesu_tone_rejection_not_success(self):
        for model,kind in [('0761','ftdx10'),('0840','ftx1'),('023','ts590')]:
            with patch.object(yac,'_cat_exchange',return_value='?;'):
                self.assertFalse(yac._tone_command(self.radio(model),kind,'CTCSS','88.5','TX'))
    def test_zero_offset_checks_value(self):
        with patch.object(yac,'_yaesu_offset_state',side_effect=[(40,False,False),(40,False,False)]),patch.object(yac,'_set_yaesu_offset'):
            self.assertFalse(yac._zero_offsets(self.radio('0840')))
    def test_tone_commands_use_documented_icom_layout(self):
        r=self.radio('IC-705'); sent=[]
        def send(r,c,d): sent.append((c,d)); return bytes.fromhex('FEFEE0A4FBFD')
        def exchange(r,c,s):
            data=b'\x03' if c==0x16 else bytes.fromhex('000023')
            return bytes([0xFE,0xFE,0xE0,0xA4,c,s])+data+b'\xfd'
        with patch.object(yac,'_civ_send',side_effect=send),patch.object(yac,'_civ_exchange',side_effect=exchange):
            self.assertTrue(yac._tone_command(r,'ic705','DCS','023','Both'))
        self.assertEqual(sent,[(0x1B,bytes.fromhex('02000023')),(0x16,bytes.fromhex('5D03'))])
    def test_labels_and_help_exist_all_languages(self):
        for lang in ['en','de','pl']:
            for label in set(re.findall(r'"(l\d{3})"', (root/'yac.py').read_text())):
                self.assertTrue((root/'lang'/lang/'labels'/label).exists(),(lang,label))
            for n in range(1,5): self.assertTrue((root/'lang'/lang/'help'/f'h{n:03d}').exists(),(lang,n))
    def test_sub_meter_uses_separate_rm_fields(self):
        r=self.radio('0840'); yac._yaesu_vfo_side=1
        responses={'FB;':'FB145500000;','MD1;':'MD14;','SM1;':'SM0130;','RM0;':'RM0130027;'}
        try:
            with patch.object(yac,'_cat_exchange',side_effect=lambda r,c:responses[c]):
                self.assertEqual(yac._radio_status(root,r,'en'),'S 2 145.5 FM')
        finally: yac._yaesu_vfo_side=0
    def test_interactive_keys_and_menu_exit_queue(self):
        # Run the real keyboard loop with hardware actions replaced by test doubles.
        # Covers nested q, help, settings and forwarding a new key out of a menu.
        for model in ['0761','0840','023','IC-705']:
            r=self.radio(model); r.serial=MagicMock()
            keys=iter(['w','f','e','m','.',',','h','w','b','.',',','h','q','s','s']+(['v'] if model=='0840' else [])+['q','i','h','b','o','o','.',',','o','.', 'q','.',',','z','?','q','y'])
            inputs=iter(['7.159','2500'])
            output=io.StringIO()
            with patch.object(yac,'connect_radio',return_value=r),patch.object(yac,'_configure_debug'),patch.object(lang_sel,'read_key',side_effect=lambda **kwargs:next(keys)),patch('builtins.input',side_effect=lambda:next(inputs)),patch.object(yac,'_current_frequency',return_value='7.159'),patch.object(yac,'_current_mode',return_value='USB'),patch.object(yac,'_current_mode_code',return_value=1 if model=='IC-705' else '2'),patch.object(yac,'_radio_status',return_value='S 7 7.159 USB') as status,patch.object(yac,'_set_frequency',return_value='7.159'),patch.object(yac,'_set_mode',return_value=True),patch.object(yac,'_band_change',return_value='40M 7.159 USB'),patch.object(yac,'_set_yac_value') as save,patch.object(yac,'_edit_tone',return_value=('enter','88.5')),patch.object(yac,'_set_tone',return_value='CTCSS 88.5 Hz Both'),patch.object(yac,'_zero_offsets',return_value=True),patch.object(yac,'_offset_action',return_value='Receive Plus 10 Hertz'),patch.object(yac,'_step_frequency',return_value='7.16'),patch.object(yac,'_round_frequency_to_khz',return_value='7.159'),redirect_stdout(output):
                self.assertEqual(yac.main([]),0)
                save.assert_called_once_with(root/'yac.ini','step_ssb','2500')
                self.assertEqual(status.call_count,2)  # Only w reads status; f is reserved.
            transcript=output.getvalue()
            self.assertIn('Bye Gena',transcript)
            self.assertNotIn('yac:',transcript)
            self.assertNotIn('Gena:',transcript)
            self.assertIn('Command not available yet.',transcript)
            r.serial.close.assert_called_once()
            yac._yaesu_vfo_side=0
    def test_response_keeps_cursor_and_next_request_starts_new_line(self):
        output=io.StringIO()
        with redirect_stdout(output):
            chat_int.show_prompt('Gena')
            chat_int.show_response('S 7 7.159 LSB')
            self.assertFalse(output.getvalue().endswith('\n'))
            chat_int.show_request('Gena','w')
            self.assertEqual(output.getvalue(),'S 7 7.159 LSB')
            chat_int.show_response('S 8 7.159 LSB')
            self.assertEqual(output.getvalue(),'S 7 7.159 LSB\nS 8 7.159 LSB')
            chat_int.show_goodbye(root,'en','Gena')
            self.assertTrue(output.getvalue().endswith('\nBye Gena\n'))
if __name__=='__main__': unittest.main(verbosity=2)
