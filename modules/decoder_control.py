"""Decoder lifecycle and keyboard/text presentation, independent of discovery."""
import logging
import math
import sys
import time
from modules.decoder_text import TextBuffer, RestoreError
from modules import chat_int, help_int, hints

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
        self.audio_pitch = None
        self.audio_wpm = None
        self.cw_buffer = self.buffer
        self.rtty_buffer = TextBuffer()
        self.ft_buffer = TextBuffer()
        self.ft_mode = 'FT8'

    def label(self, token, **values):
        return self.yac._read_label(self.root, self.language, token, '').format(**values)

    def stop(self):
        session, self.session = self.session, None
        if session:
            session.close()

    def radio_pitch(self):
        from modules.cw_control import Settings
        pitch = Settings(self.yac, self.root, self.radio, 'pitch')
        if pitch.spec is None:
            raise ValueError('Radio CW pitch is unavailable')
        value = int(pitch.read())
        if not 200 <= value <= 1500:
            raise ValueError('Radio CW pitch is outside decoder range')
        return value

    def start(self, kind, *, clear=True):
        if self.session and self.kind == kind:
            return self.label('l276')
        if kind == 'f':
            settings = self.yac._read_settings(self.root / 'yac.ini')
            if sys.platform != 'win32':
                return self.label('l129')
            if not settings.get('cw_audio_identity'):
                return hints.get_hint(self.root, self.language, 'm004')
            try:
                import sounddevice as sd
                from modules.audio_setup import resolve
                from experiments.nexus_ft8 import NexusReceive
                device = resolve(sd, settings['cw_audio_identity'])
                if device['channels'] != 1 or int(settings.get('cw_audio_channel', '1')) != 1:
                    return hints.get_hint(self.root, self.language, 'm006')
                engine = self.root / settings.get('ft_engine', '')
                output = settings.get('ft_audio_output', '')
                callsign, grid = settings.get('call', '').upper(), settings.get('ft_grid', '').upper()
                if not engine.is_file() or not all((output, callsign, grid)):
                    return hints.get_hint(self.root, self.language, 'm007')
                session = NexusReceive(self.ft_buffer.append, engine, device['name'], output,
                                       callsign, grid, self.ft_mode, self.label('l079'), self.label('l080'))
            except (ImportError, OSError, KeyError, ValueError, TypeError):
                LOG.exception('FT audio input could not be resolved')
                return self.label('l279')
        try:
            self.stop()
        except Exception:
            LOG.exception('Previous decoder restoration failed')
            return self.label('l003')
        # CW history survives stop, restart and visits to other decoder views.
        if kind != self.kind:
            self.pending = ''
        self.buffer = {'c': self.cw_buffer, 'r': self.rtty_buffer, 'f': self.ft_buffer}[kind]
        if kind in ('c', 'f'):
            clear = False
        if kind != 'f':
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
                if not any(settings.get(name, '').strip() for name in ('cw_audio_identity', 'cw_audio_device')):
                    return self.label('l279') + '. ' + hints.get_hint(self.root, self.language, 'm004')
                try:
                    self.audio_pitch = self.radio_pitch()
                except (OSError, ValueError, KeyError, TypeError):
                    LOG.exception('Radio CW pitch could not be read')
                    return self.label('l003')
                settings = dict(settings, cw_audio_pitch_hz=str(self.audio_pitch))
                if self.audio_wpm is not None:
                    settings = dict(settings, cw_audio_wpm=str(self.audio_wpm))
                session = AudioCW(self.buffer, settings)
        elif kind == 'r':
            if self.radio.model_id.casefold() != 'ic-705':
                return self.label('l129')
            from modules.rtty_decode import IcomRTTY
            session = IcomRTTY(self.yac, self.radio, self.buffer, settings)
        if clear:
            self.buffer.clear()
            self.pending = ''
        try:
            session.start()
        except RestoreError:
            LOG.exception('Decoder start rollback failed')
            return self.label('l003')
        except Exception:
            LOG.exception('Decoder start failed kind=%s model=%s', kind, self.radio.model_id)
            # Constructors own no devices; start() cleans up any partial setup.
            return self.label('l279')
        self.session, self.kind = session, kind
        if kind == 'c' and callable(getattr(session, 'speed', None)):
            self.audio_wpm = session.speed()
        return self.label('l276')

    def zero_in(self):
        from modules import cw_zero_in, split_control
        if not self.session or self.kind != 'c' or not hasattr(self.session, 'paused'):
            return self.label('l129')
        try:
            prepared = cw_zero_in.prepare(self.yac, self.root, self.radio)
        except cw_zero_in.Unsupported:
            return self.label('l129')
        except split_control.ClarifierActive as error:
            LOG.info('CW Zero In blocked: %s', error)
            return self.label('l402' if error.kind == 'rit' else 'l403')
        except (OSError, ValueError, KeyError, split_control.Unavailable, split_control.CommandFileError):
            LOG.exception('CW Zero In preflight failed')
            return self.label('l003')
        try:
            self.stop()  # Discard old queued audio and partial Morse timing.
            frequency = cw_zero_in.apply(self.yac, self.radio, prepared)
            self.audio_pitch = prepared[2]
        except split_control.ClarifierActive as error:
            LOG.info('CW Zero In blocked: %s', error)
            self.start('c', clear=False)
            return self.label('l402' if error.kind == 'rit' else 'l403')
        except (OSError, RuntimeError, ValueError, KeyError, split_control.Unavailable):
            LOG.exception('CW Zero In failed; frequency may have changed')
            self.start('c', clear=False)
            return self.label('l003')
        started = self.start('c', clear=False)
        from modules.split_control import mhz
        response = f"{self.label('l400')} {mhz(frequency)} MHz, {self.label('l401', value=self.audio_pitch)}"
        return response if self.session else response + '. ' + started

    def tick(self):
        now = time.monotonic()
        if self.session and self.kind == 'f':
            self.session.poll()
        if self.session and hasattr(self.session, 'paused') and now-self.last_audio_check >= 0.75:
            self.last_audio_check = now
            from modules import mic_gain
            spec = mic_gain.profile(self.yac, self.radio)
            # If status is unreadable, pause rather than decode our own sidetone.
            self.session.paused = True
            try:
                mode = self.yac._current_mode_code(self.radio)
                if spec and mode in ('3', '7', 3, 7):
                    if mic_gain.tx_state(self.yac, self.radio, spec) is False:
                        if callable(getattr(self.session, 'set_pitch', None)):
                            pitch = self.radio_pitch()
                            self.session.set_pitch(pitch)
                            self.audio_pitch = pitch
                        self.session.paused = False
            except (OSError, ValueError, KeyError, TypeError):
                LOG.exception('Audio decoder receive-state check failed')
        if self.session and self.session.error:
            LOG.error('Decoder input failed: %s', self.session.error)
            try:
                self.stop()
            except Exception:
                LOG.exception('Decoder restore failed')
                chat_int.show_response(self.label('l003'))
            chat_int.show_response(self.label('l284'))
        if self.kind == 'f':
            return
        self.pending += self.buffer.take()
        self.pending = self.pending[-10000:]
        if self.view and self.pending and (self.pending.endswith((' ', '\n')) or
                                          len(self.pending) >= 40 or now-self.last_output >= 2):
            if self.kind == 'c':
                chat_int.show_stream(self.pending.replace('\n', ' ').replace('\t', ' '))
            else:
                chat_int.show_response(self.pending)
            self.pending = ''
            self.last_output = now

    def review(self, position=-1, *, buffer=None):
        text = (self.buffer if buffer is None else buffer).snapshot()
        # Fixed review chunks also work for native CW streams with no line endings.
        lines = [line[i:i+60] for line in text.splitlines() for i in range(0, len(line), 60)]
        if not lines:
            return self.label('l278'), -1
        position = len(lines)-1 if position == -1 else min(len(lines)-1, max(0, position))
        return lines[position], position

    def cw_speed(self, direction=0):
        session = self.session
        if self.kind == 'c' and callable(getattr(session, 'speed', None)):
            self.audio_wpm = session.speed(direction)
            return self.label('l431', value=f'{self.audio_wpm:g}')
        if self.kind == 'c' and session is None and self.audio_wpm is not None:
            target = (math.floor(self.audio_wpm) + 1 if direction > 0 else
                      math.ceil(self.audio_wpm) - 1 if direction < 0 else self.audio_wpm)
            self.audio_wpm = max(5, min(60, target))
            return self.label('l431', value=f'{self.audio_wpm:g}')
        return self.label('l129')

    def cw_review(self, read_key):
        # Read a stable history while capture continues quietly in the background.
        was_view = self.view
        self.view = False
        text = self.buffer.snapshot()
        chunks = [line[i:i+60] for line in text.splitlines()
                  for i in range(0, len(line), 60)]
        position = max(0, len(chunks)-1)
        def announce():
            chat_int.show_response(chunks[position] if chunks else self.label('l278'))
        announce()
        try:
            while True:
                key = read_key().casefold()
                if key == 'q':
                    chat_int.show_done(self.root, self.language)
                    return
                if key == 'h':
                    chat_int.show_response(help_int.get_help(self.root, self.language, 'h052'))
                elif key in (',', '.'):
                    position = max(0, min(len(chunks)-1, position + (1 if key == '.' else -1)))
                    announce()
                elif key == 'c':
                    self.buffer.clear()
                    self.pending = ''
                    chunks = []
                    position = 0
                    chat_int.show_response(self.label('l281'))
                elif key:
                    chat_int.show_response(self.label('l129'))
        finally:
            self.view = was_view

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
                def prepare_input():
                    # Browsing is read-only; release audio only for an explicit check/save.
                    if self.session and hasattr(self.session, 'paused'):
                        self.stop()
                        chat_int.show_response(self.label('l277'))
                from modules import audio_setup
                audio_setup.control(self.yac, self.root, self.language, read_key,
                                    prepare_input=prepare_input)
            elif key in ('c', 'r'):
                chat_int.show_response(self.start(key))
                self.decoder_view(key, read_key)
            elif key == 'f':
                self.decoder_view(key, read_key)
            elif key:
                chat_int.show_response(self.label('l129'))

    def decoder_view(self, kind, read_key):
        if kind == 'f':
            chat_int.show_response(f'{self.ft_mode}. {self.label("l277")}')
        else:
            chat_int.show_response(self.label('l273' if kind == 'c' else 'l274'))
        position = -1
        self.view = kind != 'f'
        try:
            while True:
                key = read_key().casefold()
                if key == 'q':
                    if kind == 'c' or (kind == 'f' and self.kind == 'f'):
                        try:
                            self.stop()
                        except Exception:
                            LOG.exception('Decoder stop failed')
                            chat_int.show_response(self.label('l003'))
                            return
                        self.pending = ''
                        self.buffer.take()
                    chat_int.show_done(self.root, self.language)
                    return
                if key == 'h':
                    topic = {'c': 'h052', 'r': 'h053', 'f': 'h074'}[kind]
                    chat_int.show_response(help_int.get_help(self.root, self.language, topic))
                elif key == 's':
                    try:
                        if self.session and self.kind == kind:
                            self.stop()
                            response = self.label('l277')
                        else:
                            response = self.start(kind)
                    except Exception:
                        LOG.exception('Decoder stop failed')
                        response = self.label('l003')
                    chat_int.show_response(response)
                elif key == 'm' and kind == 'f':
                    if self.session and self.kind == 'f':
                        try:
                            self.stop()
                        except (OSError, RuntimeError):
                            LOG.exception('FT decoder stop failed')
                            chat_int.show_response(self.label('l003'))
                            continue
                        chat_int.show_response(self.label('l277'))
                    self.ft_mode = 'FT4' if self.ft_mode == 'FT8' else 'FT8'
                    self.ft_buffer.clear()
                    position = -1
                    chat_int.show_response(self.ft_mode)
                elif key == 'z' and kind == 'c':
                    chat_int.show_response(self.zero_in())
                elif key == 'r' and kind == 'c':
                    self.cw_review(read_key)
                elif key in ('.', ',') and kind == 'c':
                    try:
                        response = self.cw_speed(1 if key == '.' else -1)
                        if response == self.label('l129'):
                            chat_int.show_response(response)
                    except (ValueError, OSError):
                        chat_int.show_response(self.label('l003'))
                elif key == 'v' and kind == 'c':
                    try:
                        chat_int.show_response(self.yac._radio_status(self.root, self.radio, self.language))
                        chat_int.show_response(self.cw_speed())
                    except (ValueError, OSError):
                        chat_int.show_response(self.label('l003'))
                elif key in ('v', '.', ','):
                    buffer = self.ft_buffer if kind == 'f' else self.buffer
                    if key == 'v':
                        position = -1
                    elif position < 0:
                        _, position = self.review(buffer=buffer)
                        if key == ',':
                            position = max(0, position-1)
                    else:
                        position += 1 if key == '.' else -1
                        position = max(0, position)
                    response, position = self.review(position, buffer=buffer)
                    chat_int.show_response(response)
                elif key == 'n' and kind != 'c':
                    if kind == 'f':
                        self.ft_buffer.clear()
                    else:
                        self.buffer.clear()
                        self.pending = ''
                    position = -1
                    chat_int.show_response(self.label('l281'))
                elif key in ('+', '-') and self.session and self.kind == kind and hasattr(self.session, 'threshold'):
                    try:
                        value = self.session.threshold(1 if key == '+' else -1)
                        chat_int.show_response(self.label('l282', value=value))
                    except (ValueError, OSError):
                        chat_int.show_response(self.yac._radio_error(self.root, self.radio, self.language))
                elif key:
                    chat_int.show_response(self.label('l129'))
        finally:
            self.view = False

    def close(self):
        try:
            self.stop()
        except Exception:
            LOG.exception('Decoder shutdown restoration failed')
            chat_int.show_response(self.label('l003'))
