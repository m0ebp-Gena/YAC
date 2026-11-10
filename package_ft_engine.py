"""Stage a standalone, checksummed FT8 and FT4 decoder release asset."""

import argparse
import hashlib
from pathlib import Path
import zipfile

from modules.ft_engine_update import ENGINE_FILES, ENGINE_TARGETS, asset_name, check_engine_header
from update_yac import MAX_ARCHIVE


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target', choices=ENGINE_TARGETS)
    parser.add_argument('engine', type=Path)
    parser.add_argument('jimmy_source', type=Path, help='Prepared Jimmy Next checkout used for the engine build')
    parser.add_argument('--output-dir', type=Path, default=Path('builds/.work/ft-engine-assets'))
    args = parser.parse_args()

    nexus = args.jimmy_source / 'EngineHost/.nexus-src'
    files = (args.engine, args.jimmy_source / 'LICENSE', nexus / 'COPYING', nexus / 'NOTICE')
    sizes = [path.stat().st_size for path in files]
    if not all(sizes) or sum(sizes) > MAX_ARCHIVE:
        parser.error('Invalid decoder package size')
    with args.engine.open('rb') as stream:
        check_engine_header(stream.read(20), args.target)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    archive = args.output_dir / asset_name(args.target)
    checksum = archive.with_suffix('.zip.sha256')
    if archive.exists() or checksum.exists():
        parser.error('Choose an output directory without an existing decoder asset')
    with zipfile.ZipFile(archive, 'x', zipfile.ZIP_DEFLATED) as package:
        for path, name in zip(files, ENGINE_FILES):
            package.write(path, name)
    with zipfile.ZipFile(archive) as package:
        if package.testzip() is not None:
            raise ValueError('Decoder archive integrity check failed')
    data = archive.read_bytes()
    if len(data) > MAX_ARCHIVE:
        raise ValueError('Decoder archive exceeds download size limit')
    with checksum.open('x', encoding='ascii', newline='\n') as stream:
        stream.write(f'{hashlib.sha256(data).hexdigest()}  {archive.name}\n')
    print(f'Created {archive} and its SHA-256 checksum')


if __name__ == '__main__':
    main()
