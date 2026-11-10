"""Explicit receive-input selection. Never opens playback or changes defaults."""
import json
import logging
import math
from pathlib import Path
import re
import struct
import subprocess
import sys
from modules import chat_int, help_int
from modules.nexus_ft8 import alsa_pcm, audio_devices, configured_engine, require_device

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


def alsa_cw_pcm(device):
    if device['host'] != 'ALSA':
        return None
    name = device['name']
    match = re.search(r'\(hw:(\d+),(\d+)\)$', name)
    if not match:
        return alsa_pcm(name)
    try:
        card = Path(f'/proc/asound/card{match[1]}/id').read_text(encoding='ascii').strip()
    except (OSError, UnicodeError):
        return None
    return card, int(match[2])


def ft_input_key(name):
    return name if sys.platform == 'darwin' else alsa_pcm(name)


def cw_input_key(device):
    if sys.platform == 'darwin':
        return device['name'] if device['host'] == 'Core Audio' else None
    return alsa_cw_pcm(device)


def native_ft_inputs(cw_devices, ft_names):
    """Pair inputs only when both backends identify the same unique input."""
    choices = [dict(device) for device in cw_devices]
    cw_keys = [cw_input_key(device) for device in choices]
    for name in ft_names:
        key = ft_input_key(name)
        if key is not None and cw_keys.count(key) == 1:
            choices[cw_keys.index(key)]['ft_name'] = name
        else:
            choices.append(dict(name=name, channels=0, ft_name=name))
    return choices


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
    ini = root / 'yac.ini'
    settings = yac._read_settings(ini)
    ft_names = []
    if sys.platform in ('linux', 'darwin'):
        engine = configured_engine(root, settings)
        if engine.is_file():
            try:
                ft_names = audio_devices(engine, '--list-devices')
            except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired):
                LOG.exception('FT audio input enumeration failed')
    try:
        import sounddevice as sd
        all_devices = inputs(sd)
    except Exception:
        if not ft_names:
            LOG.exception('Audio input enumeration failed')
            chat_int.show_response(label('l292'))
            return
        sd, all_devices = None, []
    if not all_devices and not ft_names:
        chat_int.show_response(label('l293'))
        return
    devices = normal_inputs(all_devices)
    channel = 1
    saved = None
    try:
        if sd is not None:
            saved = resolve(sd, settings['cw_audio_identity'])
            devices = normal_inputs(all_devices, saved)
    except (KeyError, ValueError, TypeError):
        pass
    if ft_names:
        devices = native_ft_inputs(devices, ft_names)
    position = next((i for i, d in enumerate(devices)
                     if d.get('ft_name') and d['ft_name'] == settings.get('ft_audio_input')), None)
    if position is None and saved is not None:
        position = next(i for i, d in enumerate(devices) if d.get('index') == saved['index'])
    if position is not None and saved is not None and devices[position].get('index') == saved['index']:
        try:
            channel = min(saved['channels'], max(1, int(settings.get('cw_audio_channel', '1'))))
        except (ValueError, TypeError):
            position = None
    def describe():
        device = devices[position]
        token = 'l287' if device['channels'] else 'l447'
        chat_int.show_response(label(token, number=position+1, total=len(devices),
                                    name=device['name'], channel=channel,
                                    channels=device['channels']))
    described = position is not None
    if described:
        describe()
    else:
        position = 0
        has_saved = any(settings.get(key) for key in ('cw_audio_identity', 'cw_audio_device', 'ft_audio_input'))
        chat_int.show_response(label('l292' if has_saved else 'l410'))
    chat_int.show_response(label('l398'))
    chat_int.show_response(label('l399'))
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
            if not devices[position]['channels']:
                chat_int.show_response(label('l129'))
                continue
            channel = channel % devices[position]['channels'] + 1
            describe()
            described = True
        elif key in ('v', '\r', '\n'):
            if not described:
                chat_int.show_response(label('l410'))
                continue
            device = devices[position]
            ft_name = device.get('ft_name')
            if key == 'v' and not device['channels']:
                chat_int.show_response(label('l129'))
                continue
            try:
                if key != 'v' and ft_name:
                    require_device(engine, '--list-devices', ft_name)
                    if not device['channels']:
                        yac._write_yac_value(ini, 'ft_audio_input', ft_name)
                        chat_int.show_response(label('l448'))
                        return
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
                    if ft_name:
                        if cw_input_key(live) != ft_input_key(ft_name):
                            raise ValueError('CW and FT inputs no longer match')
                        yac._write_yac_value(ini, 'ft_audio_input', ft_name,
                                             cw_audio_channel=str(channel), cw_audio_identity=identity)
                    else:
                        yac._set_yac_value(ini, 'cw_audio_channel', str(channel))
                        yac._set_yac_value(ini, 'cw_audio_identity', identity)
                    chat_int.show_response(label('l290'))
                    return
            except Exception:
                LOG.exception('Audio selection/check failed')
                chat_int.show_response(label('l291'))
        elif key:
            chat_int.show_response(label('l129'))
