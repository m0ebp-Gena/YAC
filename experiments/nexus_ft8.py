"""Windows FT8 receive experiment using Jimmy Next 2.0.88's Nexus engine host."""

import argparse
import json
import os
from pathlib import Path
import secrets
import socket
import struct
import subprocess
import time


HEADER = struct.Struct('>III')
DECODE_HEADER = (0xADBCCBDA, 3, 2)
DECODE_FIELDS = struct.Struct('>BIidI')
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
CHANNEL_ENV = 'YAC_NEXUS_INPUT_CHANNEL'
CHANNEL_CAPABILITY = 'yac-input-channel-v1'


def read_text(packet, offset):
    (size,) = struct.unpack_from('>I', packet, offset)
    start = offset + 4
    end = start + size
    if end > len(packet):
        raise ValueError('Incomplete text field')
    return packet[start:end].decode('utf-8'), end


def decode_line(packet, plus='Plus', minus='Minus'):
    """Format a new, on-air decode from the Nexus host's schema 3 feed."""
    try:
        if HEADER.unpack_from(packet) != DECODE_HEADER:
            return None
        _, offset = read_text(packet, HEADER.size)  # Sending instance ID
        new, time_ms, snr, _, _ = DECODE_FIELDS.unpack_from(packet, offset)
        _, offset = read_text(packet, offset + DECODE_FIELDS.size)  # Mode marker
        message, offset = read_text(packet, offset)
        _, off_air = struct.unpack_from('>BB', packet, offset)
    except (struct.error, ValueError):
        return None

    if not new or off_air or time_ms >= 86_400_000 or not message.isprintable():
        return None
    hours, seconds = divmod(time_ms // 1000, 3600)
    minutes, seconds = divmod(seconds, 60)
    signal = str(abs(snr))
    if snr:
        signal = f'{minus if snr < 0 else plus} {signal}'
    return f'{hours:02d}:{minutes:02d}:{seconds:02d} UTC. {message}. {signal} dB.'


def require_device(engine, flag, name, *, select_channel=False):
    command = [str(engine), flag]
    if select_channel:
        command.append('--yac-channel-support')
    result = subprocess.run(
        command, cwd=engine.parent, capture_output=True, encoding='utf-8', timeout=10,
        creationflags=NO_WINDOW,
    )
    if result.returncode:
        raise RuntimeError(f'Could not list audio devices. Engine exit code {result.returncode}.')
    devices = result.stdout.splitlines()
    if select_channel:
        if devices[:1] != [CHANNEL_CAPABILITY]:
            raise RuntimeError('Nexus engine does not support selecting an input channel')
        devices = devices[1:]
    if devices.count(name) != 1:
        available = '\n'.join(devices) or 'None'
        raise RuntimeError(f'Audio device unavailable. {name}\nAvailable devices\n{available}')


def control(port, command):
    with socket.create_connection(('127.0.0.1', port), timeout=0.5) as connection:
        connection.sendall((command + '\n').encode('ascii'))
        with connection.makefile('rb') as response:
            return response.readline(1_048_576)


class NexusReceive:
    def __init__(self, output, engine, input_device, output_device, callsign, grid, mode='FT8',
                 plus='Plus', minus='Minus', *, input_channel=None):
        self.output = output
        self.engine = engine
        self.input_device = input_device
        self.input_channel = input_channel
        self.output_device = output_device
        self.callsign, self.grid, self.mode = callsign, grid, mode
        self.plus, self.minus = plus, minus
        self.listener = self.process = None
        self.error = None

    def start(self):
        if (not all((self.input_device, self.output_device, self.callsign, self.grid)) or
                self.input_device.casefold() == self.output_device.casefold()):
            raise ValueError('Configure radio input, non-radio output, callsign and grid')
        require_device(self.engine, '--list-devices', self.input_device,
                       select_channel=self.input_channel is not None)
        require_device(self.engine, '--list-output-devices', self.output_device)
        env = os.environ.copy()
        env.pop(CHANNEL_ENV, None)
        if self.input_channel is not None:
            env[CHANNEL_ENV] = str(self.input_channel)
        token = secrets.token_hex(16)
        try:
            self.listener = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.listener.bind(('127.0.0.1', 0))
            self.listener.setblocking(False)
            address, port = self.listener.getsockname()
            with socket.socket() as candidate:
                candidate.bind(('127.0.0.1', 0))
                control_port = candidate.getsockname()[1]
            # Model zero leaves CAT disconnected. Only select the receive mode
            # after confirming that the control port belongs to our child process.
            command = [
                str(self.engine), '--device', self.input_device, '--output-device', self.output_device,
                '--mycall', self.callsign, '--mygrid', self.grid,
                '--rig-model', '0', '--ptt-method', 'vox', '--control-port', str(control_port),
                '--session-token', token, '--clock-check', 'off', '--wsjtx-out', f'{address}:{port}',
            ]
            self.process = subprocess.Popen(command, cwd=self.engine.parent, stdout=subprocess.DEVNULL,
                                            stderr=subprocess.DEVNULL, env=env,
                                            creationflags=NO_WINDOW)
            deadline = time.monotonic() + 3
            while self.process.poll() is None and time.monotonic() < deadline:
                try:
                    snapshot = json.loads(control(control_port, 'SNAPSHOT'))
                except (ConnectionRefusedError, TimeoutError):
                    time.sleep(0.05)
                    continue
                if snapshot.get('sessionToken') != token:
                    raise RuntimeError('Unexpected Nexus engine on the control port')
                reply = control(control_port, f'SET_TIER {self.mode}')
                if reply.split()[:2] != [b'OK', self.mode.encode('ascii')]:
                    raise RuntimeError('Nexus engine could not select the decode mode')
                return
            raise RuntimeError(f'Nexus engine did not start. Exit code {self.process.poll()}')
        except BaseException:
            self.close()
            raise

    def poll(self):
        if self.process.poll() is not None:
            self.error = f'Nexus engine exited with code {self.process.returncode}'
            return
        # Bound the work done per YAC keyboard poll, even during a busy FT8 slot.
        for _ in range(32):
            try:
                packet = self.listener.recv(65535)
            except BlockingIOError:
                return
            except OSError as error:
                self.error = str(error)
                return
            line = decode_line(packet, self.plus, self.minus)
            if line is not None:
                self.output(line + '\n')

    def close(self):
        if self.listener is not None:
            self.listener.close()
            self.listener = None
        if self.process is not None:
            process, self.process = self.process, None
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired as error:
                raise RuntimeError('Nexus engine did not stop') from error


def receive(engine, input_device, output_device, callsign, grid):
    session = NexusReceive(lambda line: print(line, end='', flush=True), engine, input_device,
                           output_device, callsign, grid)
    try:
        session.start()
        print('Listening for FT8 decodes. Control+C stops.', flush=True)
        while not session.error:
            session.poll()
            time.sleep(0.1)
        raise RuntimeError(session.error)
    finally:
        session.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('engine', type=Path, help='Path to jimmy-engine-host.exe')
    parser.add_argument('--input', required=True, help='Exact radio audio input name')
    parser.add_argument('--output', required=True, help='Exact non-radio output name, such as PC speakers')
    parser.add_argument('--call', required=True, help='Station callsign required by the engine')
    parser.add_argument('--grid', required=True, help='Maidenhead locator required by the engine')
    args = parser.parse_args(argv)
    engine = args.engine.resolve()
    if not engine.is_file():
        parser.error(f'Engine executable unavailable at {engine}')
    if args.input.strip().casefold() == args.output.strip().casefold():
        parser.error('Choose a separate non-radio audio output')
    try:
        receive(engine, args.input, args.output, args.call.strip().upper(), args.grid.strip().upper())
    except KeyboardInterrupt:
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        parser.exit(1, f'{error}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
