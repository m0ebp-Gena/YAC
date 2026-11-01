import unittest
from types import SimpleNamespace
from unittest.mock import patch
import yac
from modules import cw_zero_in
from modules.decoder_control import DecoderManager
from modules.find_rad import RadioConnection
from tests.test_split_control import Cat, ROOT

class ZeroInTests(unittest.TestCase):
    def test_hardware_rit_reply_reports_reason_and_keeps_capture(self):
        for flag,reply in [('rit','IF00000007031000-005010300003;'),
                           ('xit','IF00000007031000-005001300003;')]:
            for lang in ('en','de','es','pl'):
                cat,exchange=self.rig()
                def incoming(radio,command):
                    if command=='IF;':
                        cat.commands.append(command)
                        return reply
                    return exchange(radio,command)
                manager=DecoderManager(yac,ROOT,cat.radio,lang)
                session=SimpleNamespace(paused=False,close=lambda:self.fail('Capture must remain running'))
                manager.session=session;manager.kind='c'
                before=dict(cat.state)
                with patch.object(yac,'_cat_exchange',side_effect=incoming), patch.object(yac,'_yaesu_vfo_side',0):
                    self.assertEqual(manager.zero_in(),manager.label('l402' if flag=='rit' else 'l403'))
                self.assertIs(manager.session,session)
                self.assertEqual(cat.state,before)
                self.assertFalse(any(c.startswith(('ZI','KP','RC','RT','XT')) for c in cat.commands))

    def test_clarifier_enabled_after_preflight_still_blocks_command(self):
        cat,exchange=self.rig()
        with patch.object(yac,'_cat_exchange',side_effect=exchange),patch.object(yac,'_yaesu_vfo_side',0):
            prepared=cw_zero_in.prepare(yac,ROOT,cat.radio)
        def incoming(radio,command):
            if command=='IF;': return 'IF00000007031000-005010300003;'
            return exchange(radio,command)
        with patch.object(yac,'_cat_exchange',side_effect=incoming):
            with self.assertRaises(cw_zero_in.split_control.ClarifierActive):
                cw_zero_in.apply(yac,cat.radio,prepared)
        self.assertFalse(any(c.startswith('ZI') for c in cat.commands))

    def rig(self, model='0840', side=0):
        cat=Cat(model,side)
        cat.state.update({'MD0':'3','MD1':'7','TX':'0','KP':'30'})
        original=cat.exchange
        def exchange(radio, command):
            if command.startswith('ZI'):
                cat.commands.append(command)
                cat.state['FA' if side==0 else 'FB']='007023123'
                return ''
            return original(radio,command)
        return cat,exchange

    def test_model_side_pitch_and_frequency_without_pitch_or_tx_setters(self):
        for model in ('0761','0800','0840'):
            for side in (0,1):
                with self.subTest(model=model,side=side):
                    cat,exchange=self.rig(model,side)
                    with patch.object(yac,'_cat_exchange',side_effect=exchange), \
                         patch.object(yac,'_yaesu_vfo_side',side), \
                         patch.object(cw_zero_in.time,'sleep'):
                        prepared=cw_zero_in.prepare(yac,ROOT,cat.radio)
                        self.assertEqual(prepared[2],600)
                        self.assertEqual(cw_zero_in.apply(yac,cat.radio,prepared),7023123)
                    self.assertIn('ZI'+str(side if model=='0840' else 0)+';',cat.commands)
                    self.assertFalse(any(c.startswith(('KP','TX','MD')) and c not in ('KP;','TX;','MD0;','MD1;') for c in cat.commands))

    def test_wrong_mode_transmit_unknown_pitch_or_side_never_retunes(self):
        for field,value in [('MD0','2'),('TX','1'),('TX','2'),('KP','99'),('KP','bad')]:
            cat,exchange=self.rig()
            cat.state[field]=value
            with patch.object(yac,'_cat_exchange',side_effect=exchange), patch.object(yac,'_yaesu_vfo_side',0):
                with self.assertRaises((ValueError, cw_zero_in.split_control.Unavailable)):
                    cw_zero_in.prepare(yac,ROOT,cat.radio)
            self.assertFalse(any(c.startswith('ZI') for c in cat.commands))
        cat,exchange=self.rig()
        with patch.object(yac,'_cat_exchange',side_effect=exchange), patch.object(yac,'_yaesu_vfo_side',0):
            prepared=cw_zero_in.prepare(yac,ROOT,cat.radio)
            cat.state['VS']='1'
            with self.assertRaises(ValueError): cw_zero_in.apply(yac,cat.radio,prepared)
        self.assertFalse(any(c.startswith('ZI') for c in cat.commands))

    def test_unprofiled_radio_returns_unsupported_without_cat(self):
        radio=RadioConnection(None,'test',115200,'CI-V','IC-705','IC-705',civ_address=164)
        with patch.object(yac,'_cat_exchange') as cat:
            with self.assertRaises(cw_zero_in.Unsupported): cw_zero_in.prepare(yac,ROOT,radio)
        cat.assert_not_called()

    def test_rejection_and_missing_frequency_are_failures(self):
        for failure in ('ZI0;','FA;'):
            cat,exchange=self.rig()
            def rejecting(radio,command):
                return '?;' if command==failure else exchange(radio,command)
            with patch.object(yac,'_cat_exchange',side_effect=exchange), patch.object(yac,'_yaesu_vfo_side',0):
                prepared=cw_zero_in.prepare(yac,ROOT,cat.radio)
            with patch.object(yac,'_cat_exchange',side_effect=rejecting), patch.object(cw_zero_in.time,'sleep'):
                with self.assertRaises((ValueError,cw_zero_in.split_control.Unavailable)):
                    cw_zero_in.apply(yac,cat.radio,prepared)

    def test_z_restarts_audio_with_pitch_preserves_text_and_does_not_save(self):
        cat,exchange=self.rig()
        cat.state['KP']='40'
        manager=DecoderManager(yac,ROOT,cat.radio,'en')
        closed=[]
        manager.session=SimpleNamespace(paused=False,close=lambda:closed.append(True))
        manager.kind='c'; manager.buffer.append('CQ TEST ')
        with patch.object(yac,'_cat_exchange',side_effect=exchange), \
             patch.object(yac,'_yaesu_vfo_side',0), \
             patch.object(yac,'_current_mode_code',return_value='3'), \
             patch.object(yac,'_read_settings',return_value={'cw_audio_device':'0'}), \
             patch.object(yac,'_set_yac_value') as save, \
             patch.object(cw_zero_in.time,'sleep'), \
             patch('modules.cw_audio.AudioCW') as audio, \
             patch('modules.chat_int.show_response') as say:
            manager.decoder_view('c',iter(['z','q']).__next__)
        self.assertTrue(closed)
        self.assertEqual(audio.call_args.args[1]['cw_audio_pitch_hz'],'700')
        self.assertIn('CQ TEST',manager.buffer.snapshot())
        save.assert_not_called()
        self.assertTrue(any('7.023123 MHz' in c.args[0] and '700 Hz' in c.args[0] for c in say.call_args_list))

    def test_labels_and_help_have_no_named_radios(self):
        for lang in ('en','de','es','pl'):
            text=(ROOT/'lang'/lang/'help/h013').read_text(encoding='utf-8')
            self.assertNotIn('FTX-1',text)
            self.assertNotIn('TS-590',text)
            self.assertNotIn('IC-705',text)
            for token in ('l400','l401'):
                label=yac._read_label(ROOT,lang,token,'')
                self.assertTrue(label)
                self.assertLessEqual(len(label.replace('{value}','')),15)
