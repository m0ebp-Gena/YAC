"""Read-only diagnostic: probe only USB identities saved in yac.ini."""
import configparser
import json
from pathlib import Path
import serial
from serial.tools import list_ports
import yac
from modules.find_rad import RadioConnection, _open_serial, _usb_identity

def main():
    root = Path(__file__).resolve().parents[2]
    config = configparser.ConfigParser()
    config.read(root / 'yac.ini')
    ports = list(list_ports.comports())
    results = []
    for section in config.sections():
        if not section.startswith('radio:') or not config[section].get('usb_identity'):
            continue
        profile = config[section]
        matches = [p for p in ports if _usb_identity(p) == profile['usb_identity']]
        preferred = sorted(matches, key=lambda p: ('Enhanced' not in p.description, 'CI-V' not in p.description, p.device))
        item = {'model': profile['model'], 'ports': [p.device for p in preferred]}
        results.append(item)
        if not preferred:
            item['result'] = 'USB interface absent'
            continue
        radio = None
        try:
            port = preferred[0].device
            conn = _open_serial(port, int(profile['baud_rate']), serial)
            radio = RadioConnection(conn, port, int(profile['baud_rate']), profile['protocol'], profile['model_id'], profile['model'], civ_address=int(profile['civ_address'], 0) if profile.get('civ_address') else None)
            item['frequency'] = yac._current_frequency(root, radio)
            item['mode'] = yac._current_mode(radio)
            item['status'] = yac._radio_status(root, radio, 'en')
            if radio.protocol == 'CI-V':
                item['offset'] = yac._icom_offset_hz(radio)
                item['rit'] = yac._icom_clarifier_enabled(radio, 1)
                item['xit'] = yac._icom_clarifier_enabled(radio, 2)
            else:
                item['offset'] = yac._yaesu_offset_state(radio)
                if yac._ftx1(radio):
                    yac._yaesu_vfo_side = 1
                    item['sub_status'] = yac._radio_status(root, radio, 'en')
                    yac._yaesu_vfo_side = 0
        except Exception as error:
            item['error'] = str(error)
        finally:
            if radio:
                radio.close()
    print(json.dumps(results, indent=2))
    (root / 'logs' / 'radio-read-check.json').write_text(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
