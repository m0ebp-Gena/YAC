import io
import json
import string
import unittest
from pathlib import Path
from contextlib import redirect_stdout
from unittest.mock import patch
import yac
from modules import filter_verify, lang_sel, verify_settings
from modules.dummy_radio import create_dummy_radio
from modules.find_rad import RadioConnection
from tests.test_verify_settings import SettingsSerial
ROOT=Path(__file__).resolve().parents[1]

class FilterVerifyTests(unittest.TestCase):
    def test_live_changes_and_all_off_are_read_only(self):
        radio=create_dummy_radio()
        original=yac._cat_exchange
        commands=[]
        def exchange(r,c):
            commands.append(c)
            return original(r,c)
        with patch.object(yac,'_cat_exchange',side_effect=exchange):
            self.assertEqual(filter_verify.verify(yac,ROOT,radio,'en'),'No Filters On')
            radio.serial.noise_blanker='1';radio.serial.noise_reduction='1';radio.serial.auto_notch='1';radio.serial.manual_notch='001';radio.serial.contour['CO00']='0001'
            expected='Filters On: NB On, NR On, Auto Notch On, Manual Notch On, Contour On'
            self.assertEqual(filter_verify.verify(yac,ROOT,radio,'en'),expected)
            self.assertNotIn('Filters',verify_settings.verify(yac,ROOT,radio,'en'))
        self.assertTrue(set(commands)<= {'MD0;','NB0;','NR0;','BC0;','BP00;','CO00;','PA0;','RA0;','PC;','AC;','EX030105;'},commands)
    def test_partial_unknown_never_claims_all_off(self):
        radio=create_dummy_radio()
        replies={'MD0;':'MD01;','NB0;':'NB01;','NR0;':'?;','BC0;':'BC00;','BP00;':'BP00000;','CO00;':'CO000000;'}
        with patch.object(yac,'_cat_exchange',side_effect=lambda r,c:replies[c]):
            self.assertEqual(filter_verify.verify(yac,ROOT,radio,'en'),'Radio Error')
            replies['NB0;']='NB00;'
            self.assertEqual(filter_verify.verify(yac,ROOT,radio,'en'),'Radio Error')
            replies['MD0;']='?;'
            self.assertEqual(filter_verify.verify(yac,ROOT,radio,'en'),'Radio Error')
    def test_ftx_sub_combined_states_only(self):
        radio=RadioConnection(None,'test',38400,'CAT','0840','0840')
        replies={'NL1;':'NL1005;','RL1;':'RL107;','BC1;':'BC10;','BP10;':'BP10001;','CO10;':'CO100001;'}
        with patch.object(yac,'_yaesu_vfo_side',1),patch.object(yac,'_current_mode_code',return_value='2'),patch.object(yac,'_cat_exchange',side_effect=lambda r,c:replies[c]) as exchange:
            self.assertEqual(filter_verify.verify(yac,ROOT,radio,'en'),'Sub receiver: Filters On: NB On, NR On, Manual Notch On, Contour On')
            self.assertEqual(exchange.call_count,5)
    def test_kenwood_shared_notch_and_nr_type(self):
        radio=RadioConnection(None,'test',38400,'CAT','023','023')
        replies={'NB;':'NB2;','NR;':'NR2;','NT;':'NT21;'}
        with patch.object(yac,'_current_mode_code',return_value='2'),patch.object(yac,'_cat_exchange',side_effect=lambda r,c:replies[c]) as exchange:
            report=filter_verify.verify(yac,ROOT,radio,'en')
            self.assertEqual(report,'Filters On: NB 2 On, NR 2 On, Manual Notch On')
            self.assertEqual(exchange.call_count,3)
            replies['NT;']='NT10;'
            self.assertIn('Auto Notch On',filter_verify.verify(yac,ROOT,radio,'en'))
            self.assertNotIn('Manual Notch',filter_verify.verify(yac,ROOT,radio,'en'))
    def test_icom_models_only_query_applicable_states(self):
        for model,address in [('IC-705',0xA4),('IC-7300',0x94),('IC-7300MK2',0xB6),('IC-7600',0x7A),('IC-9700',0xA2)]:
            serial=SettingsSerial(address)
            serial.settings.update({b'\x16\x22':b'\x01',b'\x16\x40':b'\x00',b'\x16\x41':b'\x01',b'\x16\x48':b'\x00'})
            radio=RadioConnection(serial,'test',115200,'CI-V',model,model,civ_address=address)
            with patch.object(yac,'_current_mode_code',return_value=1):
                self.assertEqual(filter_verify.verify(yac,ROOT,radio,'en'),'Filters On: NB On, Auto Notch On')
            self.assertTrue(all(len(packet)==7 for packet in serial.writes),serial.writes)
            serial.writes.clear()
            with patch.object(yac,'_current_mode_code',return_value=3):
                self.assertEqual(filter_verify.verify(yac,ROOT,radio,'en'),'Filters On: NB On')
            self.assertFalse(any(packet[4:6]==b'\x16\x41' for packet in serial.writes))
    def test_ts480_beat_cancel_and_qmx(self):
        radio=RadioConnection(None,'test',38400,'CAT','020','020');radio._ts480_variant='1'
        replies={'NB;':'NB0;','NR;':'NR1;','BC;':'BC2;'}
        with patch.object(yac,'_current_mode_code',return_value='2'),patch.object(yac,'_cat_exchange',side_effect=lambda r,c:replies[c]):
            self.assertEqual(filter_verify.verify(yac,ROOT,radio,'en'),'Filters On: NR 1 On, BC 2 On')
        del radio._ts480_variant
        with patch.object(yac,'_cat_exchange',return_value='?;') as exchange:
            self.assertEqual(filter_verify.verify(yac,ROOT,radio,'en'),'Not Supported')
            self.assertEqual(exchange.call_count,1)
    def test_verify_keeps_adjustment_and_nested_q(self):
        radio=create_dummy_radio()
        keys=iter(['f','c','l','v','.','q','v','q','v','q', 'y'])
        output=io.StringIO()
        with patch.object(yac,'connect_radio',return_value=radio),patch.object(yac,'_read_settings',return_value={'call':'test','lang':'en'}),patch.object(lang_sel,'read_key',side_effect=lambda:next(keys)),redirect_stdout(output):
            self.assertEqual(yac.main([]),0)
        self.assertEqual(radio.serial.contour['EX030202'],'-14')
        self.assertEqual(output.getvalue().count('Filters On: Contour On'),2)
    def test_repeated_v_cycles_all_statuses_and_wraps(self):
        radio=create_dummy_radio()
        radio.serial.noise_blanker='1'
        review=filter_verify.Review()
        expected=['Filters On: NB On','NB On','NR Off','Auto Notch Off','Man Notch Off','Contour Off','Filters On: NB On']
        self.assertEqual([review.next(yac,ROOT,radio,'en') for _ in expected],expected)
        review.reset()
        self.assertEqual(review.next(yac,ROOT,radio,'en'),expected[0])

    def test_review_refreshes_external_changes_and_unknowns(self):
        radio=create_dummy_radio()
        review=filter_verify.Review()
        review.next(yac,ROOT,radio,'en')
        radio.serial.noise_blanker='1'
        self.assertEqual(review.next(yac,ROOT,radio,'en'),'NB On')
        original=yac._cat_exchange
        with patch.object(yac,'_cat_exchange',side_effect=lambda r,c:'?;' if c=='NR0;' else original(r,c)):
            self.assertEqual(review.next(yac,ROOT,radio,'en'),'Radio Error')

    def test_mode_changes_restart_summary_and_skip_inapplicable(self):
        radio=create_dummy_radio()
        review=filter_verify.Review()
        review.next(yac,ROOT,radio,'en')
        review.next(yac,ROOT,radio,'en')
        radio.serial.mode='3'
        self.assertEqual(review.next(yac,ROOT,radio,'en'),'No Filters On')
        self.assertEqual(review.next(yac,ROOT,radio,'en'),'NB Off')
        self.assertEqual(review.next(yac,ROOT,radio,'en'),'NR Off')
        self.assertEqual(review.next(yac,ROOT,radio,'en'),'Man Notch Off')
        self.assertEqual(review.next(yac,ROOT,radio,'en'),'No Filters On')

    def test_keyboard_repeated_v_q_and_other_key_reset(self):
        radio=create_dummy_radio()
        keys=iter(['f','v','v','v','h','v','q','f','v','v','q','q', 'y'])
        output=io.StringIO()
        with patch.object(yac,'connect_radio',return_value=radio),patch.object(yac,'_read_settings',return_value={'call':'test','lang':'en'}),patch.object(lang_sel,'read_key',side_effect=lambda:next(keys)),redirect_stdout(output):
            self.assertEqual(yac.main([]),0)
        lines=output.getvalue()
        self.assertEqual(lines.splitlines().count('No Filters On'),3)
        self.assertEqual(lines.count('NB Off'),2)
        self.assertEqual(lines.count('NR Off'),1)

    def test_translated_fields(self):
        for number in (n for n in range(199,207) if n not in (201, 204)):
            texts=[(ROOT/f'lang/{lang}/labels/l{number}').read_text(encoding='utf-8') for lang in ['en','de','es','pl']]
            fields=lambda text:{f for _,f,_,_ in string.Formatter().parse(text) if f}
            self.assertTrue(all(text.strip() for text in texts))
            self.assertTrue(all(fields(text)==fields(texts[0]) for text in texts))

if __name__=='__main__':unittest.main()


