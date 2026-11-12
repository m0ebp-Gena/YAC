"""Decoder lifecycle and keyboard/text presentation, independent of discovery."""
from collections import deque
import logging
import math
import subprocess
import sys
import time
from modules.decoder_text import TextBuffer, RestoreError
from modules import chat_int, ft_decode_filter, help_int, hints

LOG = logging.getLogger('yac')

# Receive dial frequencies in MHz. Region-specific bands can be tuned with e.
FT_DIAL_FREQUENCIES = {
    'FT8': ('1.840', '3.573', '7.074', '10.136', '14.074', '18.100', '21.074',
            '24.915', '28.074', '50.313', '144.174', '432.065', '1296.174'),
    'FT4': ('3.575', '7.0475', '10.140', '14.080', '18.104', '21.140',
            '24.919', '28.180', '50.318', '144.170'),
}


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
        self.ft_buffer = deque(maxlen=250)
        self.ft_mode = next(iter(FT_DIAL_FREQUENCIES))
        self.ft_filter = 0
        self.ft_origin = None
        self.ft_distance = (2000, 'km')

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
            if sys.platform not in ('win32', 'linux', 'darwin'):
                return self.label('l129')
            try:
                from modules.nexus_ft8 import (NexusReceive, configured_engine,
                                              linux_receive_output, macos_receive_output)
                input_channel = None
                if sys.platform in ('linux', 'darwin'):
                    input_device = settings.get('ft_audio_input', '').strip()
                    if not input_device:
                        return hints.get_hint(self.root, self.language, 'm004')
                else:
                    if not settings.get('cw_audio_identity'):
                        return hints.get_hint(self.root, self.language, 'm004')
                    import sounddevice as sd
                    from modules.audio_setup import resolve
                    device = resolve(sd, settings['cw_audio_identity'])
                    channel = int(settings.get('cw_audio_channel', '1'))
                    if not 1 <= channel <= device['channels']:
                        return hints.get_hint(self.root, self.language, 'm006')
                    input_device = device['name']
                    if device['channels'] > 1:
                        input_channel = channel
                engine = configured_engine(self.root, settings)
                output = settings.get('ft_audio_output', '').strip()
                callsign, grid = settings.get('call', '').upper(), settings.get('ft_grid', '').upper()
                if not engine.is_file() or not all((callsign, grid)):
                    return hints.get_hint(self.root, self.language, 'm007')
                if not output and sys.platform == 'linux':
                    output = linux_receive_output(engine, input_device)
                if not output and sys.platform == 'darwin':
                    output = macos_receive_output(engine, input_device)
                if not output:
                    return hints.get_hint(self.root, self.language, 'm007')
                session = NexusReceive(lambda message, line: self.ft_buffer.append((message, line)),
                                       engine, input_device, output,
                                       callsign, grid, self.ft_mode, self.label('l079'), self.label('l080'),
                                       input_channel=input_channel)
            except (ImportError, OSError, KeyError, ValueError, TypeError, RuntimeError,
                    subprocess.TimeoutExpired):
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
        if kind != 'f':
            self.buffer = self.cw_buffer if kind == 'c' else self.rtty_buffer
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
        if kind == 'f':
            self.ft_origin = ft_decode_filter.grid_center(grid)
            self.read_ft_distance(settings)
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

    def review(self, position=-1, *, kind=None):
        if kind == 'f':
            lines = self.ft_lines()
        else:
            # Fixed review chunks also work for native CW streams with no line endings.
            lines = [line[i:i+60] for line in self.buffer.snapshot().splitlines()
                     for i in range(0, len(line), 60)]
        if not lines:
            return self.label('l278'), -1
        position = len(lines)-1 if position == -1 else min(len(lines)-1, max(0, position))
        return lines[position], position

    def ft_lines(self):
        if self.ft_filter == 2 and self.ft_distance is None:
            return []
        limit, unit = self.ft_distance or (0, 'km')
        factor = ft_decode_filter.KM_PER_MILE if unit == 'mi' else 1
        unit_label = self.label('l443') if unit == 'mi' else 'km'
        results = []
        for message, line in self.ft_buffer:
            if self.ft_filter == 1 and message.upper().split(maxsplit=1)[:1] != ['CQ']:
                continue
            distance = ft_decode_filter.message_distance(message, self.ft_origin)
            if distance is not None:
                distance /= factor
            if self.ft_filter == 2 and (distance is None or distance <= limit):
                continue
            if distance is not None:
                line = f'{line} {round(distance)} {unit_label}.'
            results.append(line)
        return results

    def read_ft_distance(self, settings):
        try:
            self.ft_distance = ft_decode_filter.distance_settings(settings)
        except ValueError:
            self.ft_distance = None

    def ft_filter_control(self, read_key):
        self.read_ft_distance(self.yac._read_settings(self.root / 'yac.ini'))
        labels = [self.label('l440'), self.label('l441'), self.ft_distance_label()]
        chat_int.show_response(labels[self.ft_filter])
        while True:
            key = read_key().casefold()
            if key == 'q':
                chat_int.show_done(self.root, self.language)
                return
            if key == 'h':
                chat_int.show_response(help_int.get_help(self.root, self.language, 'h075'))
            elif key == 'e':
                chat_int.show_response(self.ft_edit_distance(read_key))
                labels[2] = self.ft_distance_label()
            elif key in ('.', ','):
                target = (self.ft_filter + (1 if key == '.' else -1)) % len(labels)
                if target != 2 or self.ft_distance is not None:
                    self.ft_filter = target
                chat_int.show_response(labels[target])
            elif key:
                chat_int.show_response(self.label('l129'))

    def ft_distance_label(self):
        if self.ft_distance is None:
            return self.label('l356')
        limit, unit = self.ft_distance
        return self.label('l442', value=f'{limit:g}', unit=self.label('l443') if unit == 'mi' else 'km')

    def ft_edit_distance(self, read_key):
        from modules.name_call_sel import _edit_line

        unit_prompt = hints.get_hint(self.root, self.language, 'm010')
        chat_int.show_response(unit_prompt)
        key = read_key().casefold()
        while key == 'h':
            chat_int.show_response(help_int.get_help(self.root, self.language, 'h075'))
            chat_int.show_response(unit_prompt)
            key = read_key().casefold()
        if key == 'q' or not key:
            return self.label('l355')
        unit = {'k': 'km', 'm': 'mi'}.get(key)
        if unit is None:
            return self.label('l356')

        initial = ''
        if self.ft_distance is not None and self.ft_distance[1] == unit:
            initial = str(self.ft_distance[0]).removesuffix('.0')
        chat_int.finish_response()
        print(self.label('l444' if unit == 'mi' else 'l445'), flush=True)
        try:
            entered = _edit_line(initial, max_length=32).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return self.label('l355')
        if not entered:
            return self.label('l355')
        try:
            distance = ft_decode_filter.distance_settings({'ft_distance': entered, 'ft_distance_unit': unit})
        except ValueError:
            return self.label('l356')
        self.yac._set_yac_value(self.root / 'yac.ini', 'ft_distance', entered, ft_distance_unit=unit)
        self.ft_distance = distance
        self.ft_filter = 2
        return self.ft_distance_label()

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

    def restart_ft(self):
        if self.kind != 'f' or self.session is None:
            return
        try:
            self.stop()
        except (OSError, RuntimeError):
            LOG.exception('FT decoder stop failed')
            chat_int.show_response(self.label('l003'))
            return
        response = self.start('f')
        if self.session is None:
            chat_int.show_response(response)

    def ft_mode_control(self, read_key):
        modes = tuple(FT_DIAL_FREQUENCIES)
        chat_int.show_response(self.ft_mode)
        while True:
            key = read_key().casefold()
            if key == 'q':
                chat_int.show_done(self.root, self.language)
                return
            if key == 'h':
                chat_int.show_response(help_int.get_help(self.root, self.language, 'h076'))
            elif key in ('.', ','):
                direction = 1 if key == '.' else -1
                mode = modes[(modes.index(self.ft_mode) + direction) % len(modes)]
                frequency, error = self.ft_tune_preset(mode)
                if error:
                    chat_int.show_response(error)
                    continue
                if frequency is None and self.session is not None and self.kind == 'f':
                    try:
                        self.stop()
                    except (OSError, RuntimeError):
                        LOG.exception('FT decoder stop failed')
                        chat_int.show_response(self.label('l003'))
                        continue
                self.ft_mode = mode
                self.ft_buffer.clear()
                if frequency is None:
                    chat_int.show_response(f'{mode}. {hints.get_hint(self.root, self.language, "m015")}')
                else:
                    self.restart_ft()
                    chat_int.show_response(f'{mode}. {frequency} MHz' if frequency else mode)
            elif key:
                chat_int.show_response(self.label('l129'))

    def ft_tune_preset(self, mode):
        """Tune the selected mode on this band, with no CAT in Demo Mode."""
        app, root, radio, language = self.yac, self.root, self.radio, self.language
        if radio.is_dummy:
            return '', None
        if radio._yac_connection_watch.lost:
            return None, self.label('l109')
        current = app._current_frequency(root, radio)
        if current is None:
            return None, app._radio_error(root, radio, language)
        mhz = float(current)
        low, high = next(((low, high) for low, high, _, _ in app.AMATEUR_BANDS
                          if low <= mhz <= high), (mhz, mhz))
        target = next((freq for freq in FT_DIAL_FREQUENCIES[mode]
                       if low <= float(freq) <= high), None)
        if target is None:
            return None, None
        if float(target) == mhz:
            return current, None
        response = app._set_frequency(root, radio, language, target, current)
        if response.replace('.', '', 1).isdigit():
            return response, None
        return None, response

    def ft_band_control(self, read_key, watch):
        app, root, radio, language = self.yac, self.root, self.radio, self.language
        ranges = app._frequency_ranges(radio)
        presets = [(float(freq), freq) for freq in FT_DIAL_FREQUENCIES[self.ft_mode]
                   if any(low <= round(float(freq) * 1_000_000) <= high for low, high in ranges)]
        if not presets:
            chat_int.show_response(self.label('l129'))
            return
        current = app._current_frequency(root, radio)
        if current is None:
            chat_int.show_response(app._radio_error(root, radio, language))
            return
        chat_int.show_response(self.label('l090', band=app._band_name(root, language, current))
                               + f'. {current} MHz')
        while True:
            key = read_key().casefold()
            if watch.lost:
                return
            if key == 'q':
                chat_int.show_done(root, language)
                return
            if key == 'h':
                chat_int.show_response(help_int.get_help(root, language, 'h077'))
            elif key in ('.', ','):
                mhz = float(current)
                low, high = next(((low, high) for low, high, _, _ in app.AMATEUR_BANDS
                                  if low <= mhz <= high), (mhz, mhz))
                if key == '.':
                    target = next((freq for dial, freq in presets if dial > high), None)
                else:
                    target = next((freq for dial, freq in reversed(presets) if dial < low), None)
                if target is None:
                    chat_int.show_response(f'{app._band_name(root, language, current)} {current} MHz')
                    continue
                response = app._set_frequency(root, radio, language, target, current)
                if response.replace('.', '', 1).isdigit():
                    current = response
                    self.restart_ft()
                    response = f'{app._band_name(root, language, current)} {current} MHz'
                chat_int.show_response(response)
            elif key:
                chat_int.show_response(self.label('l129'))

    def decoder_view(self, kind, read_key):
        if kind == 'f':
            chat_int.show_response(hints.get_hint(self.root, self.language, 'm014'))
            frequency, error = self.ft_tune_preset(self.ft_mode)
            if error:
                response = error
            elif frequency is None:
                response = hints.get_hint(self.root, self.language, 'm015')
            else:
                response = self.start(kind)
                if frequency:
                    response = f'{frequency} MHz. {response}'
            chat_int.show_response(f'{self.ft_mode}. {response}')
        else:
            chat_int.show_response(self.label('l273' if kind == 'c' else 'l274'))
        position = -1
        pending_key = None
        self.view = kind != 'f'
        try:
            while True:
                key = pending_key if pending_key is not None else read_key().casefold()
                pending_key = None
                if key == 'q':
                    if kind == 'c' or (kind == 'f' and self.kind == 'f'):
                        try:
                            self.stop()
                        except Exception:
                            LOG.exception('Decoder stop failed')
                            chat_int.show_response(self.label('l003'))
                            return
                        self.pending = ''
                        if kind == 'c':
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
                elif key == 'd' and kind == 'f':
                    self.ft_mode_control(read_key)
                    position = -1
                elif key == 'w' and kind == 'f':
                    if self.radio._yac_connection_watch.lost:
                        chat_int.show_response(self.label('l109'))
                    else:
                        chat_int.show_response(self.yac._dispatch(
                            self.root, self.radio, self.language, 'w', None,
                        ))
                elif key in ('b', 'e', 'm') and kind == 'f':
                    watch = self.radio._yac_connection_watch
                    if watch.lost:
                        chat_int.show_response(self.label('l109'))
                    elif key == 'b':
                        self.ft_band_control(read_key, watch)
                    elif key == 'e':
                        response = self.yac._frequency_entry(self.root, self.radio, self.language)
                        if response and response.replace('.', '', 1).isdigit():
                            self.restart_ft()
                        chat_int.show_response(response)
                    else:
                        pending_key = self.yac._radio_mode_control(
                            self.root, self.radio, self.language, '', read_key, watch,
                            on_change=self.restart_ft,
                        )
                    position = -1
                elif key == 'f' and kind == 'f':
                    self.ft_filter_control(read_key)
                    position = -1
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
                    if key == 'v':
                        position = -1
                    elif position < 0:
                        _, position = self.review(kind=kind)
                        if key == ',':
                            position = max(0, position-1)
                    else:
                        position += 1 if key == '.' else -1
                        position = max(0, position)
                    response, position = self.review(position, kind=kind)
                    chat_int.show_response(response)
                elif kind != 'c' and key == ('c' if kind == 'f' else 'n'):
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
