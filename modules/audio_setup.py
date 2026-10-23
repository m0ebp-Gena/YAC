"""Explicit receive-input selection. Never opens playback or changes defaults."""
import json
import logging
import math
import struct
from modules import chat_int, help_int

LOG = logging.getLogger('yac')


def inputs(sd):
    hosts = sd.query_hostapis()
    return [dict(index=i, name=d['name'], host=hosts[d['hostapi']]['name'],
                 channels=int(d['max_input_channels']))
            for i, d in enumerate(sd.query_devices()) if d['max_input_channels'] > 0]


def resolve(sd, identity):
    saved = json.loads(identity)
    matches = [d for d in inputs(sd) if d['name'] == saved['name'] and d['host'] == saved['host']]
    if len(matches) != 1:
        raise ValueError('Saved audio input missing or ambiguous')
    return matches[0]


def level(sd, device, channel):
    # Shared input only. The user explicitly requests this one-second check.
    sd.check_input_settings(device=device, channels=channel, dtype='float32', samplerate=48000)
    with sd.RawInputStream(device=device, channels=channel, dtype='float32',
                           samplerate=48000, blocksize=960) as stream:
        data, overflow = stream.read(48000)
    if overflow:
        raise ValueError('Audio input overflow')
    values = struct.unpack('<' + 'f'*(len(data)//4), data)[channel-1::channel]
    if not values or any(not math.isfinite(v) for v in values):
        raise ValueError('Invalid audio samples')
    rms = math.sqrt(sum(v*v for v in values)/len(values))
    return round(100*rms, 1), any(abs(v) >= 0.99 for v in values)


def control(yac, root, language, read_key):
    def label(token, **values):
        return yac._read_label(root, language, token, '').format(**values)
    try:
        import sounddevice as sd
        devices = inputs(sd)
    except Exception:
        LOG.exception('Audio input enumeration failed')
        chat_int.show_response(label('l292'))
        return
    if not devices:
        chat_int.show_response(label('l293'))
        return
    settings = yac._read_settings(root/'yac.ini')
    position, channel = 0, 1
    try:
        saved = resolve(sd, settings['cw_audio_identity'])
        position = next(i for i,d in enumerate(devices) if d == saved)
        channel = min(saved['channels'], max(1, int(settings.get('cw_audio_channel', '1'))))
    except (KeyError, ValueError, TypeError):
        pass
    def describe():
        device = devices[position]
        chat_int.show_response(label('l287', number=position+1, total=len(devices),
                                    name=device['name'], host=device['host'], channel=channel,
                                    channels=device['channels']))
    chat_int.show_response(label('l286'))
    describe()
    while True:
        key = read_key().casefold()
        if key == 'q':
            chat_int.show_done(root, language)
            return
        if key == 'h':
            chat_int.show_response(help_int.get_help(root, language, 'h014'))
        elif key in ('.', ','):
            position = min(len(devices)-1, max(0, position+(1 if key == '.' else -1)))
            channel = 1
            describe()
        elif key == 'c':
            channel = channel % devices[position]['channels'] + 1
            describe()
        elif key in ('v', 'e'):
            device = devices[position]
            try:
                # Re-enumerate, so a hotplug/reordered index cannot select a microphone.
                identity = json.dumps({'name':device['name'], 'host':device['host']})
                live = resolve(sd, identity)
                if key == 'v':
                    chat_int.show_response(label('l288'))
                    value, clipped = level(sd, live['index'], channel)
                    chat_int.show_response(label('l289', value=value))
                    if clipped:
                        chat_int.show_response(label('l294'))
                else:
                    sd.check_input_settings(device=live['index'], channels=channel,
                                            dtype='float32', samplerate=48000)
                    # Save stable identity last; capture always validates both fields.
                    yac._set_yac_value(root/'yac.ini', 'cw_audio_channel', str(channel))
                    yac._set_yac_value(root/'yac.ini', 'cw_audio_identity', identity)
                    chat_int.show_response(label('l290'))
            except Exception:
                LOG.exception('Audio selection/check failed')
                chat_int.show_response(label('l291'))
        elif key:
            chat_int.show_response(label('l129'))
