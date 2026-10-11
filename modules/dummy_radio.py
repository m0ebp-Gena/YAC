"""An in-memory FT-DX10 for exploring YAC without a connected radio."""
import re

from modules.find_rad import RadioConnection


class DummySerial:
    def __init__(self):
        self.frequency = 7_159_000
        self.mode = "1"
        self.offset = 0
        self.receive = self.transmit = False
        self.tone = "000"
        self.tone_state = "0"
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
            if command == "FA":
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
            self.buffer.extend((reply + ";").encode("ascii"))
        return len(packet)


def create_dummy_radio():
    return RadioConnection(
        serial=DummySerial(), port="DEMO", baudrate=0, protocol="CAT",
        model_id="0761", model_name="FT-DX10 (demo)",
        frequency_digits="007159000", mode_code="1", is_dummy=True,
    )
