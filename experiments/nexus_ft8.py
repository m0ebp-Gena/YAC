"""Windows FT8 receive experiment using Jimmy Next 2.0.88's Nexus engine host."""

import argparse
from pathlib import Path
import socket
import struct
import subprocess


HEADER = struct.Struct('>III')
DECODE_HEADER = (0xADBCCBDA, 3, 2)
DECODE_FIELDS = struct.Struct('>BIidI')


def read_text(packet, offset):
    (size,) = struct.unpack_from('>I', packet, offset)
    start = offset + 4
    end = start + size
    if end > len(packet):
        raise ValueError('Incomplete text field')
    return packet[start:end].decode('utf-8'), end


def decode_line(packet):
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
    signal = f'Minus {-snr}' if snr < 0 else f'{snr}'
    return f'{hours:02d}:{minutes:02d}:{seconds:02d} UTC. {message}. {signal} dB.'


def require_device(engine, flag, name):
    result = subprocess.run(
        [str(engine), flag], cwd=engine.parent, capture_output=True, encoding='utf-8', timeout=10,
    )
    if result.returncode:
        raise RuntimeError(f'Could not list audio devices. Engine exit code {result.returncode}.')
    devices = result.stdout.splitlines()
    if name not in devices:
        available = '\n'.join(devices) or 'None'
        raise RuntimeError(f'Audio device unavailable. {name}\nAvailable devices\n{available}')


def receive(engine, input_device, output_device, callsign, grid):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as listener:
        listener.bind(('127.0.0.1', 0))
        listener.settimeout(1)
        address, port = listener.getsockname()
        # Model zero leaves CAT disconnected. The control socket is local and uses
        # an ephemeral port. This experiment only listens to the outbound relay.
        command = [
            str(engine), '--device', input_device, '--output-device', output_device,
            '--mycall', callsign, '--mygrid', grid,
            '--rig-model', '0', '--ptt-method', 'vox', '--control-port', '0',
            '--clock-check', 'off', '--wsjtx-out', f'{address}:{port}',
        ]
        with subprocess.Popen(command, cwd=engine.parent, stdout=subprocess.DEVNULL) as process:
            try:
                print('Listening for FT8 decodes. Control+C stops.', flush=True)
                while process.poll() is None:
                    try:
                        packet = listener.recv(65535)
                    except TimeoutError:
                        continue
                    line = decode_line(packet)
                    if line is not None:
                        print(line, flush=True)
                raise RuntimeError(f'Nexus engine exited with code {process.returncode}')
            finally:
                if process.poll() is None:
                    process.terminate()


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
        require_device(engine, '--list-devices', args.input)
        require_device(engine, '--list-output-devices', args.output)
        receive(engine, args.input, args.output, args.call.strip().upper(), args.grid.strip().upper())
    except KeyboardInterrupt:
        return 0
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        parser.exit(1, f'{error}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
