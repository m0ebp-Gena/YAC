"""Two-digit CW speed entry, immediate help/cancel and native readback."""
import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import yac
from modules import cw_control as cw
from modules.dummy_radio import create_dummy_radio
from modules.find_rad import RadioConnection

ROOT = Path(__file__).resolve().parents[1]


class SpeedTests(unittest.TestCase):
    def entry(self, radio, keys, language='en', watch=None):
        with redirect_stdout(io.StringIO()) as output:
            pending = cw.speed_entry(yac, ROOT, radio, language, iter(keys).__next__,
                                     watch or SimpleNamespace(lost=False))
        return output.getvalue(), pending

    def test_entry_immediate_help_and_q_are_read_only_all_languages(self):
        for language in ('en', 'de', 'es', 'pl'):
            radio = create_dummy_radio()
            before = dict(radio.serial.cw)
            with patch.object(yac, '_cat_exchange', wraps=yac._cat_exchange) as exchange:
                output, _ = self.entry(radio, ['h', 'q'], language)
            self.assertEqual([c.args[1] for c in exchange.call_args_list], ['KS;'])
            self.assertEqual(radio.serial.keyer_speed, '020')
            self.assertEqual(radio.serial.cw, before)
            self.assertIn(yac._read_label(ROOT, language, 'l422', '').format(value=20), output)
            self.assertIn(yac._read_label(ROOT, language, 'l354', ''), output)

    def test_help_preserves_both_typed_digits_without_enter(self):
        radio = create_dummy_radio()
        with patch.object(yac, '_cat_exchange', wraps=yac._cat_exchange) as exchange:
            self.entry(radio, ['2', '5', 'H', '\r'])
        self.assertEqual(radio.serial.keyer_speed, '025')
        self.assertEqual([c.args[1] for c in exchange.call_args_list if c.args[1] != 'KS;'], ['KS025;'])
        radio = create_dummy_radio()
        self.entry(radio, ['2', 'h', '5', '\n'])
        self.assertEqual(radio.serial.keyer_speed, '025')

    def test_one_digit_leading_zero_backspace_and_no_enter_no_write(self):
        for keys, expected in [(['4', '\r'], '004'), (['0', '4', '\r'], '004'),
                               (['2', '5', '\b', '6', '\r'], '026'),
                               (['2', '5', '\x7f', '7', '\r'], '027'),
                               (['2', '5', 'Q'], '020')]:
            radio = create_dummy_radio()
            self.entry(radio, keys)
            self.assertEqual(radio.serial.keyer_speed, expected)

    def test_blank_invalid_and_third_digit_end_without_a_write(self):
        for keys, message in [(['\r'], 'Aborted'), (['0', '\r'], 'Invalid'),
                              (['3', '\r'], 'Invalid'), (['6', '1', '\r'], 'Invalid'),
                              (['2', '0', '0'], 'Invalid'), (['-'], 'Invalid'),
                              (['²'], 'Invalid'), (['.'], 'Invalid')]:
            radio = create_dummy_radio()
            with patch.object(yac, '_cat_exchange', wraps=yac._cat_exchange) as exchange:
                output, _ = self.entry(radio, keys)
            self.assertIn(message, output)
            self.assertEqual(radio.serial.keyer_speed, '020')
            self.assertEqual([c.args[1] for c in exchange.call_args_list], ['KS;'])

    def test_cat_models_exact_wpm_range_and_native_format(self):
        for model, manufacturer in [('0761','Yaesu'), ('0800','Yaesu'), ('0840','Yaesu'), ('023','Kenwood')]:
            radio = RadioConnection(None, 'test', 38400, 'CAT', model, manufacturer)
            value = ['020']
            def exchange(radio, command):
                if command == 'KS;':
                    return 'KS' + value[0] + ';'
                self.assertRegex(command, r'^KS\d{3};$')
                value[0] = command[2:5]
                return ''
            with patch.object(yac, '_cat_exchange', side_effect=exchange):
                for wpm in range(4, 61):
                    output, _ = self.entry(radio, list(str(wpm)) + ['\r'])
                    self.assertEqual(value[0], f'{wpm:03}')
                    self.assertIn(f'Speed {wpm} WPM', output)

    def test_icom_hamlib_lookup_native_frames_and_range(self):
        anchors = {6:0, 7:7, 8:12, 20:84, 27:128, 30:144, 40:203, 48:250}
        for model, address in [('IC-705',0xa4),('IC-7300',0x94),('IC-7300MK2',0xb6),
                               ('IC-7600',0x7a),('IC-9700',0xa2)]:
            radio = RadioConnection(None,'test',115200,'CI-V',model,model,civ_address=address)
            raw = [84]
            writes = []
            def read(radio, command, sub):
                self.assertEqual((command, sub), (0x14,0x0c))
                return bytes([254,254,224,address,command,sub])+bytes.fromhex(f'{raw[0]:04}')+b'\xfd'
            def send(radio, command, data):
                self.assertEqual((command, data[0], len(data)), (0x14,0x0c,3))
                raw[0] = int(data[1:].hex())
                writes.append(raw[0])
                return bytes([254,254,224,address,251,253])
            with patch.object(yac,'_civ_exchange',side_effect=read), patch.object(yac,'_civ_send',side_effect=send):
                for wpm in range(6,49):
                    output, _ = self.entry(radio,list(str(wpm))+['\r'])
                    self.assertIn(f'Speed {wpm} WPM',output)
                    if wpm in anchors:
                        self.assertEqual(raw[0],anchors[wpm])
                for initial, expected in [(0,6),(1,7),(84,20),(85,21),(128,27),(250,48),(255,48)]:
                    raw[0]=initial
                    writes.clear()
                    output, _ = self.entry(radio,['q'])
                    self.assertIn(f'Speed {expected} WPM',output)
                    self.assertEqual(raw[0],initial)
                    self.assertEqual(writes,[])
                writes.clear()
                for invalid in ('5','49','99'):
                    output, _ = self.entry(radio,list(invalid)+['\r'])
                    self.assertIn('Invalid',output)
                self.assertEqual(writes,[])

    def test_bad_read_or_failed_readback_never_announces_success(self):
        for reply in ('', '?;', 'KS003;', 'KS061;', 'KS20;', 'KS020;KS021;'):
            with patch.object(yac,'_cat_exchange',return_value=reply) as exchange:
                output, _ = self.entry(create_dummy_radio(), [])
            self.assertNotIn('Speed 20 WPM',output)
            self.assertEqual(exchange.call_count,1)
        with patch.object(yac,'_cat_exchange',side_effect=['KS020;','','KS020;']):
            output, _ = self.entry(create_dummy_radio(), ['2','1','\r'])
        self.assertNotIn('Speed 21 WPM',output)

    def test_icom_negative_ack_and_bad_bcd_are_errors(self):
        radio=RadioConnection(None,'test',115200,'CI-V','IC-705','IC-705',civ_address=0xa4)
        prefix=b'\xfe\xfe\xe0\xa4'
        for value in (b'',b'\x00',b'\x00\xfa',b'\x02\x56'):
            with patch.object(yac,'_civ_exchange',return_value=prefix+b'\x14\x0c'+value+b'\xfd'), \
                 patch.object(yac,'_civ_send') as send:
                output,_=self.entry(radio,[])
            send.assert_not_called()
            self.assertNotIn('Speed ',output)
        with patch.object(yac,'_civ_exchange',return_value=prefix+b'\x14\x0c\x00\x84\xfd'), \
             patch.object(yac,'_civ_send',return_value=prefix+b'\xfa\xfd'):
            output,_=self.entry(radio,['2','1','\r'])
        self.assertNotIn('Speed 21 WPM',output)

    def test_disconnect_before_enter_never_writes(self):
        radio=create_dummy_radio()
        watch=SimpleNamespace(lost=False)
        def keys():
            yield '2'
            yield '5'
            watch.lost=True
            yield '\r'
        _,pending=self.entry(radio,keys(),watch=watch)
        self.assertEqual(pending,'\r')
        self.assertEqual(radio.serial.keyer_speed,'020')

    def test_main_c_k_submission_returns_to_cw(self):
        radio=create_dummy_radio()
        keys=iter(['c','k','2','5','h','\r','q','q','y'])
        with patch.object(yac,'connect_radio',return_value=radio), \
             patch.object(yac,'_read_settings',return_value={'call':'test','lang':'en'}), \
             patch.object(yac.lang_sel,'read_key',side_effect=keys.__next__), \
             patch.object(yac.time,'sleep'),redirect_stdout(io.StringIO()) as output:
            self.assertEqual(yac.main([]),0)
        self.assertIn('Speed 25 WPM',output.getvalue())
        self.assertEqual(radio.serial.keyer_speed,'025')
        self.assertEqual(radio.serial.cw['KR'],'0')
        self.assertEqual(radio.serial.cw['BI'],'0')

    def test_generic_help_and_short_translated_labels(self):
        for language,end in [('en','End of help'),('de','Ende der Hilfe'),('es','Fin de la ayuda'),('pl','Koniec pomocy')]:
            text=(ROOT/f'lang/{language}/help/h046').read_text(encoding='utf-8').strip()
            self.assertTrue(text.endswith('***\n'+end+'\n***'))
            self.assertNotRegex(text,r'Icom|Yaesu|Kenwood|FTX|IC-705')
            for number in (422,423):
                label=yac._read_label(ROOT,language,f'l{number}','')
                self.assertLessEqual(len(label.replace('{value}','')),15)


if __name__=='__main__':
    unittest.main()
