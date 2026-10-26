"""Antenna routing from live model-specific commands; no tuner changes."""
import json
import re

from modules import chat_int, help_int, ts480_control


class Unknown(Exception):
    pass


class Unsupported(Exception):
    pass


class CommandFileError(Exception):
    pass


class Antennas:
    def __init__(self, yac, root, radio):
        self.yac, self.radio = yac, radio
        path = root / radio.radio_id_path / 'antennas.json'
        try:
            self.spec = json.loads(path.read_text(encoding='utf-8')) if path.exists() else None
            if self.spec is not None and self.spec['kind'] not in {'fixed', 'ts590', 'ts480', 'ftx1', 'civ'}:
                raise ValueError('Invalid antenna definition')
        except (OSError, UnicodeError, ValueError, KeyError, TypeError) as error:
            raise CommandFileError() from error
        if self.spec and self.spec['kind'] == 'ts480' and ts480_control.variant(yac, radio) is None:
            self.spec = None

    def cat(self, command, pattern):
        match = re.fullmatch(pattern, self.yac._cat_exchange(self.radio, command).strip())
        if not match:
            raise Unknown
        return match.group(1)

    def read(self):
        kind = self.spec['kind']
        if kind == 'fixed':
            return '1'
        if kind == 'ts590':
            return self.cat('AN;', r'AN([01][01][01]);')
        if kind == 'ts480':
            return self.cat('AN;', r'AN([12]);')
        if kind == 'ftx1':
            frequency = self.yac._current_frequency(self.yac.project_root(), self.radio)
            if frequency is None:
                raise Unknown
            if not 0.03 <= float(frequency) <= 54:
                raise Unsupported
            # PC selector 2 identifies the SPA-1 power command context. Do not
            # offer SPA-1 antenna routing in the standalone Field context.
            power = self.yac._cat_exchange(self.radio, 'PC;').strip()
            if re.fullmatch(r'PC1\d{3};', power):
                raise Unsupported
            if not re.fullmatch(r'PC2\d{3};', power):
                raise Unknown
            selected = self.cat('EX030704;', r'EX030704([01]);')
            operation = self.cat('EX030703;', r'EX030703([012]);')
            return selected + operation
        command = bytes.fromhex(self.spec['read'])
        response = self.yac._civ_exchange(self.radio, command[0])
        data = self.yac._civ_response_data(response, self.radio.civ_address, command[0])
        if data is None or len(data) != 2 or data[0] not in self.spec['choices'] or data[1] not in (0, 1):
            raise Unknown
        return data

    def routes(self, state):
        kind = self.spec['kind']
        if kind == 'fixed': return '1', '1'
        if kind == 'ts480': return state, state
        if kind == 'ts590':
            tx = str(int(state[0]) + 1)
            return tx, 'RX' if state[1] == '1' else tx
        if kind == 'ftx1':
            selected, operation = state
            tx = str(int(selected) + 1) if operation == '0' else '1'
            rx = str(int(selected) + 1) if operation != '1' else '2'
            return tx, rx
        tx = str(state[0] + 1)
        return tx, 'RX' if state[1] else tx

    def write_cat(self, command, expected):
        self.yac._cat_exchange(self.radio, command)
        return self.read() == expected

    def write_civ(self, expected):
        command = bytes.fromhex(self.spec['set'])[0]
        answer = self.yac._civ_send(self.radio, command, expected)
        ack = bytes([254,254,224,self.radio.civ_address,251,253])
        return ack in answer and self.read() == expected

    def change(self, action, state):
        """Return success, unsupported, or failure. All targets come from live reads."""
        kind = self.spec['kind']
        if kind == 'fixed' or (action == 'r' and kind == 'ts480'):
            return 'unsupported'
        if kind == 'ftx1':
            selected, operation = state
            if action == 'x':
                # In receive-only modes changing HF ANT SELECT changes RX,
                # not the main TX antenna: do not disguise it as a TX cycle.
                if operation != '0': return 'unsupported'
                target = str(1-int(selected)) + operation
                return 'ok' if self.write_cat('EX030704'+target[0]+';', target) else 'failed'
            tx, rx = self.routes(state)
            if tx != '1':
                return 'select1'
            if rx == '2':
                # Select ANT1 before returning ANT2 to TRX. This keeps TX on
                # ANT1 throughout rather than briefly transmitting via ANT2.
                if not self.write_cat('EX0307040;', '0'+operation): return 'failed'
                return 'ok' if self.write_cat('EX0307030;', '00') else 'failed'
            if not self.write_cat('EX0307032;', selected+'2'): return 'failed'
            return 'ok' if self.write_cat('EX0307041;', '12') else 'failed'
        if kind == 'ts590':
            if action == 'x':
                target = str(1-int(state[0])) + state[1:]
                command = 'AN'+target[0]+'99;'
            else:
                target = state[0] + str(1-int(state[1])) + state[2]
                command = 'AN9'+target[1]+'9;'
            return 'ok' if self.write_cat(command,target) else 'failed'
        if kind == 'ts480':
            target = '2' if state == '1' else '1'
            return 'ok' if self.write_cat('AN'+target+';',target) else 'failed'
        if action == 'x':
            choices = self.spec['choices']
            if len(choices) == 1: return 'unsupported'
            target = bytes([choices[(choices.index(state[0])+1) % len(choices)],state[1]])
        else:
            target = bytes([state[0],1-state[1]])
        return 'ok' if self.write_civ(target) else 'failed'


def operate(yac, root, radio, language, action=None):
    label=lambda token,**values:yac._read_label(root,language,token,'').format(**values)
    try:
        backend=Antennas(yac,root,radio)
        if backend.spec is None: return label('l129')
        state=backend.read()
        result=backend.change(action,state) if action else 'ok'
        if result == 'unsupported': return label('l129')
        if result == 'select1': return label('l263')
        if result == 'failed':
            return yac._radio_error(root, radio, language)
        current=backend.read() if action else state
        tx,rx=backend.routes(current)
        receive = label('l261') if rx == 'RX' else rx
        response = f'{label("l260")}, TX {tx}, RX {receive}'
        return response
    except Unsupported:
        return label('l129')
    except (CommandFileError, KeyError, TypeError):
        return label('l053')
    except (Unknown,OSError,RuntimeError,ValueError):
        return yac._radio_error(root, radio, language)


def control(yac, root, radio, language, read_key, watch):
    chat_int.show_response(operate(yac,root,radio,language))
    while True:
        try:
            key=read_key().casefold()
        except (RuntimeError,OSError):
            return None
        if watch.lost: return key or 'w'
        if not key: continue
        if key == 'q':
            chat_int.show_done(root,language)
            return None
        if key == 'h':
            chat_int.show_response(help_int.get_help(root,language,'h012'))
        elif key in {'x','r'}:
            chat_int.show_response(operate(yac,root,radio,language,key))
        else:
            return key
