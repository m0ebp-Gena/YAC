"""Decoder text integrity, timing, serial interleaving and lifecycle checks."""
import math
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import yac
from modules.cw_audio import MorseTiming, ToneDecoder, MORSE
from modules.decoder_text import TextBuffer
from modules.decoder_cat import CATStream
from modules.cw_decode import KenwoodCW
from modules.rtty_decode import companion, IcomRTTY
from modules.decoder_control import DecoderManager

ROOT = Path(__file__).resolve().parents[1]


class DecoderTests(unittest.TestCase):
    def test_fragmented_unsolicited_cw_survives_cat_queries(self):
        text = TextBuffer()
        class Serial:
            data = bytearray(b'CD2C;CD')
            @property
            def in_waiting(self): return len(self.data)
            def read(self, count):
                value = bytes(self.data[:count]); del self.data[:count]; return value
            def write(self, data):
                self.data.extend(b'2Q;FA00014060000;CD2 ;CD2D;')
            def flush(self): pass
            def reset_input_buffer(self): raise AssertionError('Decoded text must not be discarded')
        radio = SimpleNamespace(serial=Serial())
        stream = CATStream(radio, text)
        radio._decoder_cat = stream
        self.assertEqual(yac._cat_exchange(radio, 'FA;'), 'FA00014060000;')
        self.assertEqual(text.snapshot(), 'CQ D')
        self.assertEqual(stream.partial, b'')

    def test_text_bounded_and_terminal_controls_not_executed(self):
        text = TextBuffer(limit=8)
        text.append('AB\x1b\x00CD\nEFGH')
        self.assertEqual(text.snapshot(), 'BCD\nEFGH')
        self.assertEqual(text.take(), 'BCD\nEFGH')
        self.assertEqual(text.take(), '')

    def test_morse_cq_with_auto_timing(self):
        timing = MorseTiming()
        output = ''
        for character in '-.-. --.-'.split():
            for symbol in character:
                timing.mark(0.06 if symbol == '.' else 0.18)
                output += timing.space(0.06)
            output += timing.space(0.18)
        self.assertEqual(output, 'CQ')
        self.assertAlmostEqual(timing.unit, 0.06)
        self.assertEqual(timing.space(0.6), ' ')
        self.assertEqual(timing.space(0.7), '')

    def test_speed_tracking_from_default_estimate(self):
        for speed in (12, 15, 25, 30, 35):
            timing = MorseTiming()
            output = ''
            for character in ('-.-.', '--.-', '-..', '.'):
                for symbol in character:
                    timing.mark(1.2/speed*(1 if symbol == '.' else 3))
                    output += timing.space(1.2/speed)
                output += timing.space(3*1.2/speed)
            self.assertEqual(output, 'CQDE')
            self.assertAlmostEqual(1.2/timing.unit, speed)

    def test_audio_cq_at_multiple_speeds_and_silence(self):
        for wpm in (12, 20, 30):
            text = TextBuffer()
            decoder = ToneDecoder(text, wpm=wpm)
            position = 0
            def audio(duration, on):
                nonlocal position
                count = round(duration*8000)
                samples = [0.2*math.sin(2*math.pi*600*(position+i)/8000) if on else 0 for i in range(count)]
                position += count
                # Deliberately unrelated chunk boundaries.
                for i in range(0, len(samples), 137): decoder.feed(samples[i:i+137])
            unit = 1.2/wpm
            audio(0.5, False)
            for symbols in ('-.-.', '--.-'):
                for symbol in symbols:
                    audio(unit*(3 if symbol == '-' else 1), True)
                    audio(unit, False)
                audio(unit*2, False)
            audio(unit*8, False)
            self.assertEqual(text.snapshot().strip(), 'CQ', wpm)

    def test_wrong_pitch_does_not_decode(self):
        text = TextBuffer()
        decoder = ToneDecoder(text)
        decoder.feed([0.2*math.sin(2*math.pi*1400*i/8000) for i in range(8000)])
        decoder.feed([0]*8000)
        self.assertEqual(text.snapshot(), '')

    def test_companion_never_uses_unrelated_radio(self):
        def port(device, serial):
            return SimpleNamespace(device=device, vid=1, pid=2, serial_number=serial, location=None)
        radio = SimpleNamespace(port='A')
        ports = [port('A','705'), port('B','705'), port('C','other')]
        self.assertEqual(companion(radio, ports), 'B')
        with self.assertRaises(ValueError): companion(radio, ports, 'C')
        with self.assertRaises(ValueError): companion(radio, ports+[port('D','705')])

    def test_native_cw_preserves_existing_ai_and_decoder(self):
        from modules.find_rad import RadioConnection
        class Serial:
            def __init__(self):
                self.data = bytearray()
                self.values = {'AI':'4', 'CD0':'0'}
                self.commands = []
            @property
            def in_waiting(self): return len(self.data)
            def read(self, count):
                value=bytes(self.data[:count]);del self.data[:count];return value
            def write(self, data):
                command=data.decode();self.commands.append(command)
                prefix = command[:3] if command.startswith('CD') else command[:2]
                value=command[len(prefix):-1]
                if value: self.values[prefix]=value
                self.data.extend((prefix+self.values[prefix]+';').encode())
            def flush(self): pass
            def reset_input_buffer(self): self.data.clear()
        serial=Serial()
        radio=RadioConnection(serial,'test',115200,'CAT','023','TS-590SG')
        receiver=KenwoodCW(yac,radio,TextBuffer())
        with patch.object(yac,'_current_mode_code',return_value='3'):
            receiver.start()
        self.assertEqual(serial.values, {'AI':'4','CD0':'1'})
        receiver.close()
        self.assertEqual(serial.values, {'AI':'4','CD0':'0'})
        self.assertNotIn('AI2;', serial.commands)
        self.assertIsNone(radio._decoder_cat)

    def test_icom_settings_read_write_and_reject(self):
        radio = SimpleNamespace(civ_address=0xA4)
        values = {bytes.fromhex('050133'): 0}
        def exchange(radio, command, data):
            prefix=bytes.fromhex('FEFEE0A4')
            key=data[:3]
            if len(data)==4:
                values[key]=data[3]
                return prefix+b'\xfb\xfd'
            return prefix+b'\x1a'+key+bytes([values[key],253])
        receiver=IcomRTTY(yac,radio,TextBuffer(),{})
        with patch.object(yac,'_civ_send',side_effect=exchange):
            self.assertEqual(receiver.setting('0133'),0)
            self.assertEqual(receiver.setting('0133',1),1)
            receiver.previous=0
            receiver.restore_needed=True
            receiver.close()
            self.assertEqual(values[bytes.fromhex('050133')],0)
        with patch.object(yac,'_civ_send',return_value=bytes.fromhex('FEFEE0A4FAFD')):
            with self.assertRaises(ValueError): receiver.setting('0133',1)

    def test_icom_keying_assignments_block_port_open(self):
        from modules.find_rad import RadioConnection
        import serial.tools.list_ports
        radio=RadioConnection(None,'A',115200,'CI-V','IC-705','IC-705',civ_address=0xA4)
        ports=[SimpleNamespace(device=name,vid=1,pid=2,serial_number='705',location=None) for name in ('A','B')]
        for blocked in ('0125','0126','0127'):
            receiver=IcomRTTY(yac,radio,TextBuffer(),{})
            with patch.object(yac,'_current_mode_code',return_value=4), \
                 patch.object(serial.tools.list_ports,'comports',return_value=ports), \
                 patch.object(receiver,'setting',side_effect=lambda n: 3 if n==blocked else 0), \
                 patch('modules.find_rad._open_serial') as opened:
                with self.assertRaises(ValueError): receiver.start()
                opened.assert_not_called()

    def test_native_decoder_failed_restore_detaches_serial_reader(self):
        from modules.decoder_text import RestoreError
        radio=SimpleNamespace(protocol='CAT',model_id='023')
        receiver=KenwoodCW(yac,radio,TextBuffer())
        radio._decoder_cat=receiver.stream
        receiver.previous=('0','0')
        with patch.object(yac,'_cat_exchange',return_value='?;'):
            with self.assertRaises(RestoreError): receiver.close()
        self.assertIsNone(radio._decoder_cat)

    def test_audio_pauses_for_tx_and_unknown_state(self):
        from modules.find_rad import RadioConnection
        radio=RadioConnection(None,'test',115200,'CAT','0840','FTX-1')
        manager=DecoderManager(yac,ROOT,radio,'en')
        manager.session=SimpleNamespace(paused=True,error=None)
        with patch.object(yac,'_current_mode_code',return_value='3'), \
             patch('modules.mic_gain.tx_state',return_value=False):
            manager.tick()
            self.assertFalse(manager.session.paused)
        for state in (True,None):
            manager.last_audio_check=0
            with patch.object(yac,'_current_mode_code',return_value='3'), \
                 patch('modules.mic_gain.tx_state',return_value=state):
                manager.tick()
                self.assertTrue(manager.session.paused)

    def test_back_keeps_capture_explicit_stop_closes(self):
        session=SimpleNamespace(close=lambda: None,error=None)
        manager=DecoderManager(yac,ROOT,SimpleNamespace(),'en')
        manager.session=session;manager.kind='c'
        with patch('modules.chat_int.show_response'), patch('modules.chat_int.show_back'):
            manager.decoder_view('c',iter(['q']).__next__)
        self.assertIs(manager.session,session)
        with patch.object(session,'close') as close, patch('modules.chat_int.show_response'), patch('modules.chat_int.show_back'):
            manager.decoder_view('c',iter(['e','q']).__next__)
            close.assert_called_once()
        self.assertIsNone(manager.session)


if __name__ == '__main__':
    unittest.main()
