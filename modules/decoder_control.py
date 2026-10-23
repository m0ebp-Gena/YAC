"""Decoder lifecycle and keyboard/text presentation, independent of discovery."""
import logging
import time
from modules.decoder_text import TextBuffer, RestoreError
from modules import chat_int, help_int

LOG = logging.getLogger('yac')


class DecoderManager:
    def __init__(self, yac, root, radio, language):
        self.yac, self.root, self.radio, self.language = yac, root, radio, language
        self.buffer = TextBuffer()
        self.session = None
        self.kind = None
        self.view = False
        self.pending = ''
        self.last_output = time.monotonic()
        self.last_audio_check = 0

    def label(self, token, **values):
        return self.yac._read_label(self.root, self.language, token, '').format(**values)

    def stop(self):
        session, self.session = self.session, None
        if session:
            session.close()

    def start(self, kind):
        if self.session and self.kind == kind:
            return self.label('l276')
        try:
            self.stop()
        except Exception:
            LOG.exception('Previous decoder restoration failed')
            return self.label('l280')
        settings = self.yac._read_settings(self.root / 'yac.ini')
        if kind == 'c':
            if self.radio.protocol == 'CAT' and self.radio.model_id == '023':
                from modules.cw_decode import KenwoodCW
                session = KenwoodCW(self.yac, self.radio, self.buffer)
            else:
                from modules.cw_audio import AudioCW
                from modules import mic_gain
                if mic_gain.profile(self.yac, self.radio) is None:
                    return self.label('l129')
                mode = self.yac._current_mode_code(self.radio)
                if mode not in ('3', '7', 3, 7):
                    return self.label('l285')
                session = AudioCW(self.buffer, settings)
        else:
            if self.radio.model_id.casefold() != 'ic-705':
                return self.label('l129')
            from modules.rtty_decode import IcomRTTY
            session = IcomRTTY(self.yac, self.radio, self.buffer, settings)
        self.buffer.clear()
        self.pending = ''
        try:
            session.start()
        except RestoreError:
            LOG.exception('Decoder start rollback failed')
            return self.label('l280')
        except Exception:
            LOG.exception('Decoder start failed kind=%s model=%s', kind, self.radio.model_id)
            # Constructors own no devices; start() cleans up any partial setup.
            return self.label('l279')
        self.session, self.kind = session, kind
        return self.label('l276')

    def tick(self):
        now = time.monotonic()
        if self.session and hasattr(self.session, 'paused') and now-self.last_audio_check >= 0.75:
            self.last_audio_check = now
            from modules import mic_gain
            spec = mic_gain.profile(self.yac, self.radio)
            # If status is unreadable, pause rather than decode our own sidetone.
            self.session.paused = True
            try:
                mode = self.yac._current_mode_code(self.radio)
                if spec and mode in ('3', '7', 3, 7):
                    self.session.paused = mic_gain.tx_state(self.yac, self.radio, spec) is not False
            except (OSError, ValueError):
                LOG.exception('Audio decoder receive-state check failed')
        if self.session and self.session.error:
            LOG.error('Decoder input failed: %s', self.session.error)
            try:
                self.stop()
            except Exception:
                LOG.exception('Decoder restore failed')
                chat_int.show_response(self.label('l280'))
            chat_int.show_response(self.label('l284'))
        self.pending += self.buffer.take()
        self.pending = self.pending[-10000:]
        if self.view and self.pending and (self.pending.endswith((' ', '\n')) or
                                          len(self.pending) >= 40 or now-self.last_output >= 2):
            chat_int.show_response(self.pending)
            self.pending = ''
            self.last_output = now

    def review(self, position=-1):
        text = self.buffer.snapshot()
        # Fixed review chunks also work for native CW streams with no line endings.
        lines = [line[i:i+60] for line in text.splitlines() for i in range(0, len(line), 60)]
        if not lines:
            return self.label('l278'), -1
        position = len(lines)-1 if position == -1 else min(len(lines)-1, max(0, position))
        return lines[position], position

    def control(self, read_key):
        chat_int.show_response(self.label('l272'))
        while True:
            key = read_key().casefold()
            if key == 'q':
                chat_int.show_back(self.root, self.language)
                return
            if key == 'h':
                chat_int.show_response(help_int.get_help(self.root, self.language, 'h013'))
            elif key == 'a':
                # Release an existing audio input before the explicit level check.
                if self.session and hasattr(self.session, 'paused'):
                    try:
                        self.stop()
                        chat_int.show_response(self.label('l277'))
                    except Exception:
                        chat_int.show_response(self.label('l280'))
                        continue
                from modules import audio_setup
                audio_setup.control(self.yac, self.root, self.language, read_key)
            elif key in ('c', 'r'):
                chat_int.show_response(self.start(key))
                self.decoder_view(key, read_key)
            elif key:
                chat_int.show_response(self.label('l129'))

    def decoder_view(self, kind, read_key):
        chat_int.show_response(self.label('l273' if kind == 'c' else 'l274'))
        position = -1
        self.view = True
        try:
            while True:
                key = read_key().casefold()
                if key == 'q':
                    chat_int.show_done(self.root, self.language)
                    return
                if key == 'h':
                    chat_int.show_response(help_int.get_help(self.root, self.language, 'h013'))
                elif key == 'e':
                    try:
                        if self.session and self.kind == kind:
                            self.stop()
                            response = self.label('l277')
                        else:
                            response = self.start(kind)
                    except Exception:
                        LOG.exception('Decoder stop failed')
                        response = self.label('l280')
                    chat_int.show_response(response)
                elif key in ('v', '.', ','):
                    if key == 'v':
                        position = -1
                    elif position < 0:
                        _, position = self.review()
                        if key == ',':
                            position = max(0, position-1)
                    else:
                        position += 1 if key == '.' else -1
                        position = max(0, position)
                    response, position = self.review(position)
                    chat_int.show_response(response)
                elif key == 'n':
                    self.buffer.clear()
                    self.pending = ''
                    position = -1
                    chat_int.show_response(self.label('l281'))
                elif key in ('+', '-') and self.session and self.kind == kind and hasattr(self.session, 'threshold'):
                    try:
                        value = self.session.threshold(1 if key == '+' else -1)
                        chat_int.show_response(self.label('l282', value=value))
                    except (ValueError, OSError):
                        chat_int.show_response(self.label('l131'))
                elif key:
                    chat_int.show_response(self.label('l129'))
        finally:
            self.view = False

    def close(self):
        try:
            self.stop()
        except Exception:
            LOG.exception('Decoder shutdown restoration failed')
            chat_int.show_response(self.label('l280'))
