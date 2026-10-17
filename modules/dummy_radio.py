"""An in-memory FT-DX10 for exploring YAC without a connected radio."""
import re

from modules.find_rad import RadioConnection


class DummySerial:
    def __init__(self):
        self.frequency = 7_159_000
        self.mode = "1"
        self.split_settings = {'VS': '0', 'ST': '0', 'FT': '0',
                               'FB': '007159000', 'MD1': '1', 'OS0': '0',
                               'EX010317': '0100', 'EX010318': '0600'}
        self.bandwidth = "20"
        self.noise_blanker = '0'
        self.nb_level = '005'
        self.noise_reduction = '0'
        self.nr_level = '05'
        self.auto_notch = '0'
        self.manual_notch = '000'
        self.notch_position = '120'
        self.notch_width = '0'
        self.contour = {'CO00': '0000', 'CO01': '1200', 'EX030202': '-15', 'EX030203': '10'}
        self.offset = 0
        self.receive = self.transmit = False
        self.tone = "000"
        self.tone_state = "0"
        self.gains = {"AG0": 128, "RG0": 255, "SQ0": 0}
        self.preamp = "0"
        self.attenuator = "0"
        self.power = "020"
        self.mic_gain = 50
        self.agc = '6'
        self.processor_on = False
        self.processor_level = 25
        self.tuner = "000"
        self.tuner_selection = "0"
        self.buffer = bytearray()
        self.is_open = True
        self.timeout = 0.01

    @property
    def in_waiting(self):
        return len(self.buffer)

    def reset_input_buffer(self):
        self.buffer.clear()

    def flush(self):
        pass

    def close(self):
        self.is_open = False

    def read(self, count):
        data = bytes(self.buffer[:count])
        del self.buffer[:count]
        return data

    def write(self, packet):
        for command in packet.decode("ascii").split(";"):
            if not command:
                continue
            reply = "?"
            prefix = next((p for p in self.contour if command.startswith(p)), None)
            if command in {'IF', 'OI'}:
                other = command == 'OI'
                frequency = self.split_settings['FB'] if other else f'{self.frequency:09d}'
                mode = self.split_settings['MD1'] if other else self.mode
                reply = command + '000' + frequency + '+000000' + mode + '00000'
            elif command in self.split_settings:
                reply = command + self.split_settings[command]
            elif any(command.startswith(key) for key in self.split_settings):
                key = next(key for key in sorted(self.split_settings, key=len, reverse=True) if command.startswith(key))
                value = command[len(key):]
                if key == 'FT':
                    value = {'2': '0', '3': '1'}.get(value, value)
                self.split_settings[key] = value
                reply = command
            elif prefix:
                if command != prefix:
                    self.contour[prefix] = command[len(prefix):]
                reply = prefix + self.contour[prefix]
            elif command in self.gains:
                reply = f"{command}{self.gains[command]:03d}"
            elif re.fullmatch(r"(?:AG0|RG0|SQ0)\d{3}", command):
                self.gains[command[:3]] = int(command[3:])
                reply = command
            elif command == 'BC0':
                reply = 'BC0' + self.auto_notch
            elif re.fullmatch(r'BC0[01]', command):
                self.auto_notch = command[-1]
                reply = command
            elif command in {'BP00', 'BP01'}:
                reply = command + (self.manual_notch if command == 'BP00' else self.notch_position)
            elif re.fullmatch(r'BP00(?:000|001)', command):
                self.manual_notch = command[4:]
                reply = command
            elif re.fullmatch(r'BP01\d{3}', command):
                self.notch_position = command[4:]
                reply = command
            elif command == 'EX030204':
                reply = command + self.notch_width
            elif re.fullmatch(r'EX030204[01]', command):
                self.notch_width = command[-1]
                reply = command
            elif command == 'NR0':
                reply = 'NR0' + self.noise_reduction
            elif re.fullmatch(r'NR0[01]', command):
                self.noise_reduction = command[-1]
                reply = command
            elif command == 'RL0':
                reply = 'RL0' + self.nr_level
            elif re.fullmatch(r'RL0\d{2}', command):
                self.nr_level = command[3:]
                reply = command
            elif command == 'NB0':
                reply = 'NB0' + self.noise_blanker
            elif re.fullmatch(r'NB0[01]', command):
                self.noise_blanker = command[-1]
                reply = command
            elif command == 'NL0':
                reply = 'NL0' + self.nb_level
            elif re.fullmatch(r'NL0\d{3}', command):
                self.nb_level = command[3:]
                reply = command
            elif command == "SH0":
                reply = "SH00" + self.bandwidth
            elif re.fullmatch(r"SH00\d{2}", command):
                self.bandwidth = command[4:]
                reply = command
            elif command == "FA":
                reply = f"FA{self.frequency:09d}"
            elif re.fullmatch(r"FA\d{9}", command):
                self.frequency = int(command[2:])
                reply = command
            elif command == "MD0":
                reply = f"MD0{self.mode}"
            elif re.fullmatch(r"MD0[1-9A-F]", command):
                self.mode = command[3]
                reply = command
            elif command == "ID":
                reply = "ID0761"
            elif command == "SM0":
                reply = "SM0130"
            elif command in {"BU0", "BD0"}:
                bands = [1900000, 3750000, 5357000, 7150000, 10125000,
                         14175000, 18118000, 21225000, 24940000, 28850000, 52000000]
                index = min(range(len(bands)), key=lambda i: abs(bands[i] - self.frequency))
                index = max(0, min(len(bands) - 1, index + (1 if command == "BU0" else -1)))
                self.frequency = bands[index]
                self.mode = "1" if self.frequency < 14000000 else "2"
                reply = command
            elif command == "CF001":
                reply = f"CF001{'-' if self.offset < 0 else '+'}{abs(self.offset):04d}"
            elif re.fullmatch(r"CF001[+-]\d{4}", command):
                self.offset = int(command[5:])
                reply = command
            elif command == "CF000":
                reply = f"CF000{int(self.receive)}{int(self.transmit)}000"
            elif re.fullmatch(r"CF000[01][01]000", command):
                self.receive, self.transmit = command[5] == "1", command[6] == "1"
                reply = command
            elif command == "CN00":
                reply = f"CN00{self.tone}"
            elif re.fullmatch(r"CN00\d{3}", command):
                self.tone = command[4:]
                reply = command
            elif command == "CT0":
                reply = f"CT0{self.tone_state}"
            elif re.fullmatch(r"CT0[012]", command):
                self.tone_state = command[3]
                reply = command
            elif command == "PA0":
                reply = "PA0" + self.preamp
            elif re.fullmatch(r"PA0[012]", command):
                self.preamp = command[-1]
                reply = command
            elif command == "RA0":
                reply = "RA0" + self.attenuator
            elif re.fullmatch(r"RA0[0123]", command):
                self.attenuator = command[-1]
                reply = command
            elif command == "PR0":
                reply = 'PR0' + ('2' if self.processor_on else '1')
            elif command in {'PR01', 'PR02'}:
                self.processor_on = command[-1] == '2'
                reply = command
            elif command == "PL":
                reply = f'PL{self.processor_level:03d}'
            elif re.fullmatch(r'PL\d{3}', command):
                self.processor_level = int(command[2:])
                reply = command
            elif command == "RM3":
                reply = 'RM3000000'
            elif command == "GT0":
                reply = 'GT0' + self.agc
            elif re.fullmatch(r'GT0[01234]', command):
                self.agc = '6' if command[-1] == '4' else command[-1]
                reply = 'GT0' + self.agc
            elif command == "MG":
                reply = f"MG{self.mic_gain:03d}"
            elif re.fullmatch(r"MG\d{3}", command):
                self.mic_gain = int(command[2:])
                reply = command
            elif command == "TX":
                reply = "TX0"
            elif command == "RM4":
                reply = "RM4000000"
            elif command == "PC":
                reply = "PC" + self.power
            elif re.fullmatch(r"PC\d{3}", command):
                self.power = command[2:]
                reply = command
            elif command == "AC":
                reply = "AC" + self.tuner
            elif re.fullmatch(r"AC00[01]", command):
                self.tuner = command[2:]
                reply = command
            elif command == "EX030105":
                reply = command + self.tuner_selection
            elif re.fullmatch(r"EX030105[0123]", command):
                self.tuner_selection = command[-1]
                reply = command
            self.buffer.extend((reply + ";").encode("ascii"))
        return len(packet)


def create_dummy_radio():
    return RadioConnection(
        serial=DummySerial(), port="DEMO", baudrate=0, protocol="CAT",
        model_id="0761", model_name="FT-DX10 (demo)",
        frequency_digits="007159000", mode_code="1", is_dummy=True,
    )
