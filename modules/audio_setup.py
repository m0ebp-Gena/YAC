"""Explicit receive-input selection. Never opens playback or changes defaults."""
import json
import logging
import math
import struct
import sys
from modules import chat_int, help_int

LOG = logging.getLogger('yac')


def inputs(sd):
    hosts = sd.query_hostapis()
    return [dict(index=i, name=d['name'], host=hosts[d['hostapi']]['name'],
                 channels=int(d['max_input_channels']))
            for i, d in enumerate(sd.query_devices()) if d['max_input_channels'] > 0]


def normal_inputs(devices, saved=None):
    """One plain list; prefer full Windows endpoint names, retaining saved input."""
    if sys.platform == 'win32':
        choices = []
        for host in ('Windows WASAPI', 'WASAPI', 'Windows DirectSound', 'MME'):
            choices = [d for d in devices if d['host'] == host and d['name'] not in {
                'Microsoft Sound Mapper - Input', 'Primary Sound Capture Driver'}]
            if choices:
                break
        if not choices:
            choices = [d for d in devices if d['host'] == devices[0]['host']] if devices else []
    else:
        choices = list(devices)
    if saved is not None and saved not in choices:
        # Retain the actual saved interface, rather than silently migrating
        # capture. A unique identical full name needs no second list entry.
        same_name = [i for i, d in enumerate(choices) if d['name'] == saved['name']]
        if len(same_name) == 1:
            choices[same_name[0]] = saved
        else:
            choices.append(saved)
    return choices


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


def control(yac, root, language, read_key, *, prepare_input=None):
    def label(token, **values):
        return yac._read_label(root, language, token, '').format(**values)
    try:
        import sounddevice as sd
        all_devices = inputs(sd)
    except Exception:
        LOG.exception('Audio input enumeration failed')
        chat_int.show_response(label('l292'))
        return
    if not all_devices:
        chat_int.show_response(label('l293'))
        return
    devices = normal_inputs(all_devices)
    settings = yac._read_settings(root/'yac.ini')
    position, channel = 0, 1
    saved_available = False
    try:
        saved = resolve(sd, settings['cw_audio_identity'])
        devices = normal_inputs(all_devices, saved)
        position = next(i for i,d in enumerate(devices) if d == saved)
        channel = min(saved['channels'], max(1, int(settings.get('cw_audio_channel', '1'))))
        saved_available = True
    except (KeyError, ValueError, TypeError):
        pass
    def describe():
        device = devices[position]
        chat_int.show_response(label('l287', number=position+1, total=len(devices),
                                    name=device['name'], host=device['host'], channel=channel,
                                    channels=device['channels']))
    if saved_available:
        describe()
    else:
        chat_int.show_response(label('l292' if settings.get('cw_audio_identity') or settings.get('cw_audio_device') else 'l410'))
    chat_int.show_response(label('l398'))
    chat_int.show_response(label('l399'))
    described = saved_available
    while True:
        key = read_key().casefold()
        if key == 'q':
            chat_int.show_done(root, language)
            return
        if key == 'h':
            help_int.show_paged(root, language, help_int.get_help(root, language, 'h014'), read_key)
        elif key in ('.', ','):
            if described:
                position = min(len(devices)-1, max(0, position+(1 if key == '.' else -1)))
            channel = 1
            describe()
            described = True
        elif key == 'c':
            channel = channel % devices[position]['channels'] + 1
            describe()
            described = True
        elif key in ('v', '\r', '\n'):
            if not described:
                chat_int.show_response(label('l410'))
                continue
            device = devices[position]
            try:
                # Re-enumerate, so a hotplug/reordered index cannot select a microphone.
                identity = json.dumps({'name':device['name'], 'host':device['host']})
                live = resolve(sd, identity)
                if prepare_input is not None:
                    prepare_input()
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
                    return
            except Exception:
                LOG.exception('Audio selection/check failed')
                chat_int.show_response(label('l291'))
        elif key:
            chat_int.show_response(label('l129'))
