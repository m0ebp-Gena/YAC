"""Read-only, line-oriented identity and connection information."""
import json
import re

from modules import chat_int, help_int, region_plan


def _clean(value):
    # Device strings and CAT responses must not inject terminal controls/lines.
    return ' '.join(''.join(c for c in str(value) if c.isprintable()).split())


def report(yac, root, radio, language):
    lines = []
    demo = getattr(radio, 'is_dummy', False)
    profile_path = (root / 'rad_cmds' / 'demo' if demo else root / radio.radio_id_path)
    try:
        spec = json.loads((profile_path / 'information.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        spec = {}

    def add(token, value):
        if value is not None and str(value).strip():
            lines.append(f"{chat_int.label(root, language, token)}: {_clean(value)}")

    details = getattr(radio, 'port_details', {}) or {}
    if demo:
        details = spec.get('usb', details)
    add('l378', details.get('description'))
    add('l379', details.get('product'))
    add('l380', details.get('interface'))
    if details.get('vid') and details.get('pid'):
        add('l381', f"{details['vid']}:{details['pid']}")
    add('l382', details.get('serial_number'))
    add('l383', radio.port)
    if not demo:
        add('l384', getattr(radio.serial, 'baudrate', None) or radio.baudrate)
    add('l385', radio.protocol)
    if radio.civ_address is not None:
        add('l386', f'{radio.civ_address:02X}')
    add('l387', region_plan.selected(yac._read_settings(root / 'yac.ini')))

    maker = {'yaesu': 'Yaesu', 'kenwood': 'Kenwood', 'icom': 'Icom'}.get(
        radio.manufacturer_key, '')
    model = radio.model_name
    extra = dict(spec.get('simulated', {})) if demo else {}
    maker = spec.get('manufacturer', maker)
    model = spec.get('model', model)
    for query in spec.get('queries', []):
        if query.get('requires') and query['requires'] not in extra:
            continue
        if query.get('unless') and query['unless'] in extra:
            continue
        try:
            answer = yac._cat_exchange(radio, query['read']).strip()
            match = re.fullmatch(query['pattern'], answer)
            if not match:
                continue
            value = match.group(1)
            if query.get('values'):
                value = query['values'].get(value)
            if value:
                extra[query['field']] = value
                if query.get('manufacturer'):
                    maker = query['manufacturer']
                if query.get('model'):
                    model = query['model']
                if query.get('stop'):
                    break
        except (OSError, RuntimeError, ValueError):
            continue
    # A compatible CAT ID alone does not prove a TS-480 or a QMX.
    if radio.protocol == 'CAT' and radio.model_id == '020' and not extra:
        maker = ''
        model = chat_int.label(root, language, 'l392')
        add('l393', '020')
    add('l391', extra.get('processor'))
    add('l395', extra.get('serial'))
    add('l396', extra.get('year'))
    add('l388', maker)
    add('l390', extra.get('variant'))
    add('l389', model or chat_int.label(root, language, 'l392'))
    add('l394', extra.get('firmware'))
    return '\n'.join(lines)


def control(yac, root, radio, language, read_key, watch=None):
    chat_int.show_response(report(yac, root, radio, language))
    while True:
        try:
            key = read_key().casefold()
        except (EOFError, KeyboardInterrupt):
            chat_int.show_done(root, language)
            return
        if watch is not None and watch.lost:
            return
        if key == 'i':
            chat_int.show_response(report(yac, root, radio, language))
        elif key == 'h':
            chat_int.show_response(help_int.get_help(root, language, 'h036'))
        elif key == 'q':
            chat_int.show_done(root, language)
            return
