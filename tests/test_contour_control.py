import io
import unittest
from pathlib import Path
from unittest.mock import patch
from contextlib import redirect_stdout
import yac
from modules import contour_control as contour, filter_control, lang_sel
from modules.dummy_radio import create_dummy_radio
from modules.find_rad import RadioConnection
ROOT=Path(__file__).resolve().parents[1]

class ContourTests(unittest.TestCase):
    def test_each_model_side_and_live_signed_level(self):
        for model,menu in [('0761','EX030202'),('0800','EX030205'),('0840','EX030305')]:
            radio=RadioConnection(None,'test',38400,'CAT',model,model)
            side='1' if model=='0840' else '0'
            width=menu[:-1]+str(int(menu[-1])+1)
            state={f'CO{side}0':'0000',f'CO{side}1':'3000',menu:'-01',width:'05'}
            commands=[]
            def exchange(r,c):
                commands.append(c)
                prefix=next(p for p in state if c.startswith(p))
                if c!=prefix+';': state[prefix]=c[len(prefix):-1]
                return prefix+state[prefix]+';'
            with patch.object(yac,'_current_mode_code',return_value='2'),patch.object(yac,'_yaesu_vfo_side',1),patch.object(yac,'_cat_exchange',side_effect=exchange):
                self.assertEqual(contour.operate(yac,ROOT,radio,'en',toggle=True),'Contour On')
                self.assertEqual(contour.operate(yac,ROOT,radio,'en',direction=1),'Contour frequency 3010 hertz')
                self.assertEqual(contour.operate(yac,ROOT,radio,'en',parameter='level',direction=1),'Contour level Neutral')
                self.assertIn(menu+'+00;',commands)
                self.assertEqual(contour.operate(yac,ROOT,radio,'en',parameter='level',direction=1),'Contour level Peak 1')
                self.assertEqual(contour.operate(yac,ROOT,radio,'en',parameter='width',direction=-1),'Contour width 4')
                self.assertEqual(contour.operate(yac,ROOT,radio,'en',toggle=True),'Contour Off')
                before=dict(state)
                for parameter in ['frequency','level','width']:
                    self.assertEqual(contour.operate(yac,ROOT,radio,'en',parameter=parameter,direction=1),'Contour Off')
                self.assertEqual(state,before)
    def test_limits_and_failed_readback(self):
        radio=create_dummy_radio()
        radio.serial.contour.update({'CO00':'0001','CO01':'3200','EX030202':'-40','EX030203':'11'})
        self.assertEqual(contour.operate(yac,ROOT,radio,'en',direction=1),'Contour frequency 3200 hertz')
        self.assertEqual(contour.operate(yac,ROOT,radio,'en',parameter='level',direction=-1),'Contour level Dip 40')
        self.assertEqual(contour.operate(yac,ROOT,radio,'en',parameter='width',direction=1),'Contour width 11')
        with patch.object(yac,'_current_mode_code',return_value='2'),patch.object(yac,'_cat_exchange',side_effect=lambda r,c:'CO000001;' if c=='CO00;' else 'CO013000;'):
            self.assertEqual(contour.operate(yac,ROOT,radio,'en',direction=1),'Contour change failed')
    def test_unknown_and_unsupported_never_write(self):
        radio=create_dummy_radio()
        with patch.object(yac,'_current_mode_code',return_value='4'),patch.object(yac,'_cat_exchange') as exchange:
            self.assertEqual(contour.operate(yac,ROOT,radio,'en',toggle=True),'Not supported')
            exchange.assert_not_called()
        with patch.object(yac,'_current_mode_code',return_value='2'),patch.object(yac,'_cat_exchange',return_value='?;') as exchange:
            self.assertEqual(contour.operate(yac,ROOT,radio,'en',toggle=True),'Contour setting unknown')
            self.assertEqual(exchange.call_count,1)
    def test_menu_level_width_frequency_and_q_context(self):
        radio=create_dummy_radio()
        keys=iter(['f','c','l','.','w',',','c','.','c','.','q','l','q','q','q', 'y'])
        output=io.StringIO()
        with patch.object(yac,'connect_radio',return_value=radio),patch.object(yac,'_read_settings',return_value={'call':'test','lang':'en'}),patch.object(lang_sel,'read_key',side_effect=lambda:next(keys)),redirect_stdout(output):
            self.assertEqual(yac.main([]),0)
        self.assertEqual(radio.serial.contour['EX030202'],'-14')
        self.assertEqual(radio.serial.contour['EX030203'],'09')
        self.assertEqual(radio.serial.contour['CO01'],'1210')
        self.assertEqual(radio.serial.contour['CO00'],'0000')
        self.assertIn('Contour level Dip 14',output.getvalue())
        self.assertIn('Contour width 9',output.getvalue())
        self.assertIn('Contour frequency 1200 hertz',output.getvalue())

if __name__=='__main__': unittest.main()

