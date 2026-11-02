"""Pitch/volume navigation, context help, native menus and read-only entry."""
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


class PitchVolumeTests(unittest.TestCase):
    def adjust(self, radio, name, keys, language='en', watch=None):
        with redirect_stdout(io.StringIO()) as output:
            pending = cw.adjustment(yac, ROOT, radio, language, name, iter(keys).__next__,
                                    watch or SimpleNamespace(lost=False))
        return output.getvalue(), pending

    def test_entry_repeat_context_help_and_exit_preserve_both_settings(self):
        for language in ('en','de','es','pl'):
            for name, letter, topic in [('pitch','p','h047'),('volume','v','h048')]:
                radio=create_dummy_radio(); radio.serial.mode='3'
                before=dict(radio.serial.cw)
                with patch.object(yac,'_cat_exchange',wraps=yac._cat_exchange) as exchange, \
                     patch.object(cw.help_int,'get_help',wraps=cw.help_int.get_help) as help_call:
                    output,_=self.adjust(radio,name,[letter,'h','q'],language)
                help_call.assert_called_once_with(ROOT,language,topic)
                allowed={'KP;'} if name=='pitch' else {'MD0;','ML1;'}
                self.assertTrue(set(c.args[1] for c in exchange.call_args_list)<=allowed)
                self.assertEqual(radio.serial.cw_pitch,'30')
                self.assertEqual(radio.serial.sidetone_volume,'050')
                self.assertEqual(radio.serial.cw,before)
                self.assertIn(yac._read_label(ROOT,language,'l354',''),output)

    def test_yaesu_full_pitch_and_volume_ranges_do_not_wrap(self):
        for model in ('0761','0800','0840'):
            radio=RadioConnection(None,'test',38400,'CAT',model,model)
            for name,prefix,width,maximum in [('pitch','KP',2,75),('volume','ML1',3,100)]:
                raw=[0];writes=[]
                def exchange(radio,command):
                    if command==prefix+';': return prefix+str(raw[0]).zfill(width)+';'
                    self.assertTrue(command.startswith(prefix))
                    raw[0]=int(command[len(prefix):-1]);writes.append(raw[0]);return ''
                backend=cw.Delay(yac,ROOT,radio,name)
                with patch.object(yac,'_cat_exchange',side_effect=exchange), \
                     patch.object(yac,'_current_mode_code',return_value='3'):
                    backend.change(-1);self.assertEqual(writes,[])
                    for value in range(1,maximum+1):
                        actual=backend.change(1)
                        self.assertEqual(actual,str(300+10*value) if name=='pitch' else str(value))
                    writes.clear();backend.change(1);self.assertEqual(writes,[])
                    for value in reversed(range(maximum)):
                        backend.change(-1);self.assertEqual(raw[0],value)

    def test_shared_yaesu_volume_selects_cw_but_keeps_volume_unchanged(self):
        radio=create_dummy_radio()
        with patch.object(yac,'_cat_exchange',wraps=yac._cat_exchange) as exchange:
            output,_=self.adjust(radio,'volume',['q'])
        self.assertIn(yac._mode_name(radio,'3'),output)
        self.assertIn('Sidetone 50',output)
        commands=[c.args[1] for c in exchange.call_args_list]
        self.assertEqual([c for c in commands if c not in ('MD0;','ML1;')],['MD03;'])
        self.assertLess(commands.index('MD03;'),commands.index('ML1;'))
        self.assertEqual(radio.serial.mode,'3')
        self.assertEqual(radio.serial.sidetone_volume,'050')
        with patch.object(yac,'_current_mode_code',side_effect=['3','3','3','1']), \
             patch.object(yac,'_cat_exchange',wraps=yac._cat_exchange) as exchange:
            output,_=self.adjust(radio,'volume',['.','q'])
        self.assertIn('Not Supported',output)
        self.assertEqual([c.args[1] for c in exchange.call_args_list],['ML1;','ML1;'])
        self.assertEqual(radio.serial.sidetone_volume,'050')

    def test_volume_preserves_existing_cw_u_and_cw_l_all_languages(self):
        for mode in ('3','7'):
            for language in ('en','de','es','pl'):
                radio=create_dummy_radio();radio.serial.mode=mode
                with patch.object(yac,'_set_mode',wraps=yac._set_mode) as setter:
                    self.adjust(radio,'volume',['h','v','q'],language)
                setter.assert_not_called()
                self.assertEqual(radio.serial.mode,mode)
                self.assertEqual(radio.serial.sidetone_volume,'050')

    def test_volume_mode_failure_never_reads_or_sets_volume(self):
        radio=create_dummy_radio()
        with patch.object(yac,'_set_mode',return_value=False), \
             patch.object(yac,'_cat_exchange',wraps=yac._cat_exchange) as exchange:
            output,_=self.adjust(radio,'volume',[])
        self.assertNotIn('Sidetone ',output)
        self.assertEqual([c.args[1] for c in exchange.call_args_list],['MD0;'])
        with patch.object(yac,'_current_mode_code',return_value=None), \
             patch.object(yac,'_set_mode') as setter,patch.object(yac,'_cat_exchange') as exchange:
            self.adjust(radio,'volume',[])
        setter.assert_not_called();exchange.assert_not_called()

    def test_ftx_volume_changes_only_selected_receiver_mode(self):
        radio=create_dummy_radio();radio.model_id='0840'
        with patch.object(yac,'_yaesu_vfo_side',1), \
             patch.object(yac,'_cat_exchange',wraps=yac._cat_exchange) as exchange:
            self.adjust(radio,'volume',['q'])
        self.assertEqual(radio.serial.split_settings['MD1'],'3')
        self.assertEqual(radio.serial.mode,'1')
        self.assertIn('MD13;',[c.args[1] for c in exchange.call_args_list])
        self.assertEqual(radio.serial.sidetone_volume,'050')

    def test_icom_exact_dedicated_menu_read_write_and_all_steps(self):
        profiles=[('IC-705',0xa4,'050249'),('IC-7300',0x94,'050158'),
                  ('IC-7300MK2',0xb6,'050218'),('IC-7600',0x7a,'050024'),('IC-9700',0xa2,'050221')]
        for model,address,selector in profiles:
            radio=RadioConnection(None,'test',115200,'CI-V',model,model,civ_address=address)
            raw={'pitch':128,'volume':128};writes=[]
            prefix=bytes([254,254,224,address])
            def exchange(radio,command,sub):
                self.assertEqual((command,sub),(0x14,0x09))
                return prefix+b'\x14\x09'+bytes.fromhex(f"{raw['pitch']:04}")+b'\xfd'
            def send(radio,command,data):
                if command==0x1a:
                    self.assertEqual(data[:3],bytes.fromhex(selector))
                    if len(data)==3:
                        return prefix+b'\x1a'+data+bytes.fromhex(f"{raw['volume']:04}")+b'\xfd'
                    self.assertEqual(len(data),5)
                    raw['volume']=int(data[3:].hex());writes.append(('volume',raw['volume']))
                else:
                    self.assertEqual((command,data[0],len(data)),(0x14,0x09,3))
                    raw['pitch']=int(data[1:].hex());writes.append(('pitch',raw['pitch']))
                return prefix+b'\xfb\xfd'
            with patch.object(yac,'_civ_exchange',side_effect=exchange),patch.object(yac,'_civ_send',side_effect=send):
                for name,letter,lo,hi,step in [('pitch','p',300,900,5),('volume','v',0,100,1)]:
                    backend=cw.Delay(yac,ROOT,radio,name)
                    raw[name]=0;writes.clear()
                    self.adjust(radio,name,[letter,'h','q'])
                    self.assertEqual(writes,[])
                    self.assertEqual(raw[name],0)
                    self.assertEqual(backend.change(-1),str(lo));self.assertEqual(writes,[])
                    for value in range(lo+step,hi+1,step):
                        self.assertEqual(backend.change(1),str(value))
                    writes.clear();self.assertEqual(backend.change(1),str(hi));self.assertEqual(writes,[])
                    for value in reversed(range(lo,hi,step)):
                        self.assertEqual(backend.change(-1),str(value))
                    for code in range(256):
                        raw[name]=code
                        self.assertIn(backend.read(),backend.spec['choices'])
                        before=dict(raw);writes.clear()
                        self.adjust(radio,name,[letter,'q'])
                        self.assertEqual(raw,before);self.assertEqual(writes,[])

    def test_icom_menu_read_must_echo_the_exact_selector(self):
        radio=RadioConnection(None,'test',115200,'CI-V','IC-705','IC-705',civ_address=0xa4)
        prefix=b'\xfe\xfe\xe0\xa4'
        for body in (b'\x05\x02\x50\x00\x50',b'\x05\x02\x49',
                     b'\x05\x02\x49\x00\xfa',b'\x05\x02\x49\x02\x56',b'\x05\x02\x49\x00\x50\x00'):
            with patch.object(yac,'_civ_send',return_value=prefix+b'\x1a'+body+b'\xfd') as send:
                output,_=self.adjust(radio,'volume',[])
            self.assertNotIn('Sidetone ',output)
            self.assertEqual(send.call_count,1)
            self.assertEqual(send.call_args.args[1:],(0x1a,b'\x05\x02\x49'))

    def test_failed_change_is_not_announced_as_success(self):
        radio=create_dummy_radio();radio.serial.mode='3'
        for name,old,new,reply in [('pitch','Pitch 600 Hz','Pitch 610 Hz','KP30;'),
                                   ('volume','Sidetone 50','Sidetone 51','ML1050;')]:
            with patch.object(yac,'_current_mode_code',return_value='3'), \
                 patch.object(yac,'_cat_exchange',side_effect=[reply,reply,'',reply]):
                output,_=self.adjust(radio,name,['.','q'])
            self.assertIn(old,output);self.assertNotIn(new,output)

    def test_radio_front_panel_changes_are_read_before_adjusting(self):
        for name,letter,attribute,start,expected in [('pitch','p','cw_pitch','40','41'),
                                                    ('volume','v','sidetone_volume','070','071')]:
            radio=create_dummy_radio();radio.serial.mode='3'
            def keys():
                setattr(radio.serial,attribute,start)
                yield '.'
                yield 'q'
            self.adjust(radio,name,keys())
            self.assertEqual(getattr(radio.serial,attribute),expected)

    def test_unsupported_profiles_and_disconnect_do_not_write(self):
        radio=RadioConnection(None,'test',38400,'CAT','023','TS-590SG')
        with patch.object(yac,'_cat_exchange') as exchange:
            for name in ('pitch','volume'):
                output,_=self.adjust(radio,name,[])
                self.assertIn('Not Supported',output)
        exchange.assert_not_called()
        radio=create_dummy_radio();radio.serial.mode='3'
        for name in ('pitch','volume'):
            _,pending=self.adjust(radio,name,['.'],watch=SimpleNamespace(lost=True))
            self.assertEqual(pending,'w' if name=='volume' else '.')
        self.assertEqual(radio.serial.cw_pitch,'30')
        self.assertEqual(radio.serial.sidetone_volume,'050')

    def test_main_p_and_v_stay_in_cw_and_keep_values_on_q(self):
        radio=create_dummy_radio();radio.serial.mode='3'
        keys=iter(['c','p','.','p','h','q','v','.','v','h','q','q','q','y'])
        with patch.object(yac,'connect_radio',return_value=radio), \
             patch.object(yac,'_read_settings',return_value={'call':'test','lang':'en'}), \
             patch.object(yac.lang_sel,'read_key',side_effect=keys.__next__), \
             patch.object(yac.time,'sleep'),redirect_stdout(io.StringIO()) as output:
            self.assertEqual(yac.main([]),0)
        self.assertIn('Pitch 610 Hz',output.getvalue())
        self.assertIn('Sidetone 51',output.getvalue())
        self.assertEqual(radio.serial.cw_pitch,'31')
        self.assertEqual(radio.serial.sidetone_volume,'051')
        self.assertEqual(radio.serial.cw['BI'],'0')
        self.assertEqual(radio.serial.cw['KR'],'0')

    def test_translated_context_help_has_distinct_titles_and_boundaries(self):
        for language,end in [('en','End of help'),('de','Ende der Hilfe'),('es','Fin de la ayuda'),('pl','Koniec pomocy')]:
            pitch=(ROOT/f'lang/{language}/help/h047').read_text(encoding='utf-8').strip()
            volume=(ROOT/f'lang/{language}/help/h048').read_text(encoding='utf-8').strip()
            self.assertNotEqual(pitch.splitlines()[0],volume.splitlines()[0])
            for text in (pitch,volume):
                self.assertTrue(text.endswith('***\n'+end+'\n***'))
                self.assertNotRegex(text,r'Icom|Yaesu|Kenwood|FTX|IC-705')
            for number in (424,425):
                label=yac._read_label(ROOT,language,f'l{number}','')
                self.assertLessEqual(len(label.replace('{value}','')),15)


if __name__=='__main__':
    unittest.main()
