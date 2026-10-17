"""Audio CW receiver, with timing adapted from Carl Obermeier's CWKit.

CWKit Copyright (c) 2026 Carl Obermeier, MIT; see doc/CWKit-LICENSE.txt.
Adapted from Sources/CWKit/Morse/MorseDecoder.swift in captobie/cwdecode.
The simple fixed-tone audio detector here is YAC's, not CWKit's pipeline.
"""
from collections import deque
import math
import queue
import threading

MORSE = dict(zip(
    '.- -... -.-. -.. . ..-. --. .... .. .--- -.- .-.. -- -. --- .--. --.- .-. ... - ..- ...- .-- -..- -.-- --.. '
    '----- .---- ..--- ...-- ....- ..... -.... --... ---.. ----. .-.-.- --..-- ..--.. -..-. -...- .-.-. -....- .--.-.'.split(),
    'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.,?/=+-@'))


def clusters(values, ratio):
    short, long = min(values), max(values)
    if short <= 0:
        return None
    for _ in range(8):
        split = math.sqrt(short * long)
        a, b = [v for v in values if v < split], [v for v in values if v >= split]
        if not a or not b:
            return None
        short, long = sum(a)/len(a), sum(b)/len(b)
    return (short, long) if long/short >= ratio else None


class MorseTiming:
    def __init__(self, wpm=20):
        self.dit = 1.2/wpm
        self.dah = self.dit*3
        self.marks = deque(maxlen=16)
        self.gaps = deque(maxlen=16)
        self.pending = []
        self.last_gap = None
        self.word_units = 5
        self.character_ended = self.word_ended = True

    @property
    def unit(self):
        return (self.dah-self.dit)/2

    @property
    def bias(self):
        return min(max(self.dit-self.unit, -0.4*self.unit), 0.4*self.unit)

    def mark(self, duration):
        if duration <= 0:
            return
        if self.last_gap is not None:
            units = (self.last_gap+self.bias)/self.unit
            if 2 <= units < 3*self.word_units:
                self.gaps.append(units)
                if len(self.gaps) >= 2:
                    groups = clusters(self.gaps, 1.6)
                    self.word_units = sum(groups)/2 if groups else max(5, 1.4*sum(self.gaps)/len(self.gaps))
        self.last_gap = None
        self.marks.append(min(duration, 8*self.dit))
        if len(self.marks) >= 3:
            groups = clusters(self.marks, 2)
            if groups:
                self.dit, self.dah = groups
            else:
                mean = sum(self.marks)/len(self.marks)
                if abs(math.log(mean/self.dit)) <= abs(math.log(mean/self.dah)):
                    self.dit = mean
                else:
                    self.dah = mean
            if self.dah > 4.5*self.dit:
                self.dit = self.dah/4.5
            self.dah = max(self.dah, 2*self.dit)
        if len(self.pending) < 10:
            self.pending.append(duration)
        self.character_ended = self.word_ended = False

    def space(self, duration):
        self.last_gap = duration
        gap = duration + self.bias
        result = ''
        if not self.character_ended and gap >= 2*self.unit:
            symbols = ''.join('.' if v < (self.dit+self.dah)/2 else '-' for v in self.pending)
            result = MORSE.get(symbols, '?')
            self.pending = []
            self.character_ended = True
        if self.character_ended and not self.word_ended and gap >= self.word_units*self.unit:
            result += ' '
            self.word_ended = True
        return result


class ToneDecoder:
    """10 ms blocks at 8 kHz; fixed pitch, level and tone-energy gates."""
    def __init__(self, output, pitch=600, threshold=0.01, wpm=20):
        self.output = output
        self.pitch, self.threshold = pitch, threshold
        self.timing = MorseTiming(wpm)
        self.state = False
        self.duration = 0
        self.partial = []

    def feed(self, samples):
        self.partial.extend(samples)
        while len(self.partial) >= 80:
            block, self.partial = self.partial[:80], self.partial[80:]
            # Correlate the wanted pitch; noise/other tones must not key it.
            energy = sum(v*v for v in block)/80
            real = sum(v*math.cos(2*math.pi*self.pitch*i/8000) for i,v in enumerate(block))/80
            imag = sum(v*math.sin(2*math.pi*self.pitch*i/8000) for i,v in enumerate(block))/80
            tone = 2*(real*real+imag*imag)
            down = energy >= self.threshold**2 and tone >= energy*(0.35 if self.state else 0.55)
            if down != self.state:
                if self.state and self.duration >= 0.02:
                    self.timing.mark(self.duration)
                self.duration = 0
                self.state = down
            self.duration += 0.01
            if not down:
                self.output.append(self.timing.space(self.duration))


class AudioCW:
    def __init__(self, output, settings):
        self.output, self.settings = output, settings
        self.stream = None
        self.error = None
        self.queue = queue.Queue(maxsize=100)
        self.stop_event = threading.Event()
        self.worker = None
        self.paused = True

    def start(self):
        import sounddevice as sd
        identity = self.settings.get('cw_audio_identity', '').strip()
        device = self.settings.get('cw_audio_device', '').strip()
        if identity:
            from modules.audio_setup import resolve
            device = resolve(sd, identity)['index']
        elif not device:
            raise ValueError('Configure radio audio input first')
        elif device.isdigit():
            device = int(device)
        info = sd.query_devices(device, 'input')
        channel = int(self.settings.get('cw_audio_channel', '1'))
        if not 1 <= channel <= info['max_input_channels']:
            raise ValueError('Invalid audio channel')
        pitch = int(self.settings.get('cw_audio_pitch_hz', '600'))
        threshold = float(self.settings.get('cw_audio_threshold', '0.01'))
        wpm = float(self.settings.get('cw_audio_wpm', '20'))
        if not 200 <= pitch <= 1500 or not 0 < threshold <= 1 or not 5 <= wpm <= 60:
            raise ValueError('Invalid audio decoder settings')
        self.decoder = ToneDecoder(self.output, pitch, threshold, wpm)
        import struct
        def callback(data, frames, timing, status):
            if status:
                self.error = str(status)
                return
            samples = struct.unpack('<' + 'f'*(len(data)//4), data)
            try:
                self.queue.put_nowait(samples[channel-1::channel])
            except queue.Full:
                self.error = 'Audio decoder overflow'
        self.stream = sd.RawInputStream(device=device, samplerate=48000, channels=channel,
                                        dtype='float32', blocksize=960, callback=callback)
        self.worker = threading.Thread(target=self._run, daemon=True)
        try:
            self.worker.start()
            self.stream.start()
        except Exception:
            self.close()
            raise

    def _run(self):
        was_paused = True
        while not self.stop_event.is_set():
            try:
                samples = self.queue.get(timeout=0.1)
            except queue.Empty:
                continue
            if self.paused:
                was_paused = True
                continue
            if was_paused:
                old = self.decoder
                self.decoder = ToneDecoder(self.output, old.pitch, old.threshold,
                                            1.2/old.timing.unit)
                was_paused = False
            # USB radio audio commonly uses 48 kHz. Average each six samples
            # before decimating to the timing detector's 8 kHz stream.
            self.decoder.feed([sum(samples[i:i+6])/6 for i in range(0, len(samples)-5, 6)])

    def close(self):
        self.stop_event.set()
        if self.stream:
            self.stream.close()
            self.stream = None
        if self.worker:
            self.worker.join(timeout=1)
