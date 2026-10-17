"""TS-590SG's native CW text stream. No transmit commands are used."""
import re
from modules.decoder_cat import CATStream
from modules.decoder_text import RestoreError


class KenwoodCW:
    def __init__(self, yac, radio, output):
        self.yac, self.radio = yac, radio
        self.stream = CATStream(radio, output)
        self.previous = None

    @property
    def error(self):
        return self.stream.error

    def query(self, command, pattern):
        match = re.search(pattern, self.yac._cat_exchange(self.radio, command))
        if not match:
            raise ValueError('Unconfirmed decoder state')
        return match.group(1)

    def start(self):
        if self.radio.protocol != 'CAT' or self.radio.model_id != '023':
            raise ValueError('Unsupported native CW decoder')
        mode = self.yac._current_mode_code(self.radio)
        if mode not in ('3', '7'):
            raise ValueError('Select CW mode first')
        ai = self.query('AI;', r'AI([024]);')
        decoder = self.query('CD0;', r'CD0([01]);')
        self.previous = ai, decoder
        self.radio._decoder_cat = self.stream
        self.stream.start()
        try:
            self.yac._cat_exchange(self.radio, 'CD01;')
            if self.query('CD0;', r'CD0([01]);') != '1':
                raise ValueError('Decoder enable failed')
            if ai == '0':
                self.yac._cat_exchange(self.radio, 'AI2;')
            if self.query('AI;', r'AI([024]);') == '0':
                raise ValueError('Decoded character output unavailable')
        except Exception:
            self.close()
            raise

    def threshold(self, direction):
        current = int(self.query('CD1;', r'CD1(\d{3});'))
        if not 1 <= current <= 30:
            raise ValueError('Unknown threshold')
        target = min(30, max(1, current + direction))
        self.yac._cat_exchange(self.radio, f'CD1{target:03d};')
        if int(self.query('CD1;', r'CD1(\d{3});')) != target:
            raise ValueError('Threshold change failed')
        return target

    def close(self):
        failed = False
        try:
            if self.previous:
                ai, decoder = self.previous
                for command, value, pattern in [('CD0', decoder, r'CD0([01]);'),
                                                 ('AI', ai, r'AI([024]);')]:
                    self.yac._cat_exchange(self.radio, command + value + ';')
                    if self.query(command + ';', pattern) != value:
                        failed = True
        except (OSError, ValueError):
            failed = True
        finally:
            self.stream.close()
            self.radio._decoder_cat = None
            self.previous = None
        if failed:
            raise RestoreError('Decoder settings restoration unconfirmed')
