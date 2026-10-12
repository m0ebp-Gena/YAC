"""Publish current packages at the root; archive only release artifacts."""
from datetime import date
import json
from pathlib import Path
import time


def _move(source, destination):
    """Allow sync scanners a brief opportunity to release a newly written file."""
    for attempt in range(6):
        try:
            source.rename(destination)
            return
        except PermissionError as error:
            if getattr(error, 'winerror', None) not in {32, 33} or attempt == 5:
                raise
            time.sleep(0.5)


def publish(root: Path, release_date: str, artifacts: list[Path]) -> list[Path]:
    date.fromisoformat(release_date)
    root = root.resolve()
    builds = (root / 'builds').resolve()
    staging = (builds / '.work').resolve()
    runnable = (builds / 'runnable').resolve()
    previous = (root / 'previous-builds').resolve()
    for directory in (builds, staging, runnable, previous):
        if not directory.is_relative_to(root):
            raise ValueError('Build directories must stay within the project')
    sources = [path.resolve() for path in artifacts]
    if not sources or len({path.name for path in sources}) != len(sources):
        raise ValueError('Build artifacts must have distinct names')
    for path in sources:
        if not path.is_relative_to(staging):
            raise ValueError('Publish only staged artifacts within builds/.work')
        if not path.exists():
            raise FileNotFoundError(path)
    outputs = [runnable / path.name if path.is_dir() else root / path.name for path in sources]
    marker = staging / 'current-release.json'
    state = json.loads(marker.read_text()) if marker.exists() else {'date': release_date, 'artifacts': []}
    date.fromisoformat(state['date'])
    current = []
    for name in state['artifacts']:
        path = (root / name).resolve()
        if not path.is_relative_to(root) or (path.parent != root and path.parent != runnable):
            raise ValueError('Invalid current release artifact')
        if path.exists():
            current.append(path)
    if any(path.exists() and path not in current for path in outputs):
        raise FileExistsError('A destination exists outside the current release')
    if current and (state['date'] != release_date or any(path.exists() for path in outputs)):
        history = previous / state['date']
        destination = history
        run = 2
        while destination.exists():
            destination = history / f'{run:03}'
            run += 1
        destination = destination.resolve()
        if not destination.is_relative_to(previous):
            raise ValueError('Archive must stay within previous-builds')
        destination.mkdir(parents=True)
        for path in current:
            _move(path, destination / path.name)
        current = []
    for source, destination in zip(sources, outputs):
        destination.parent.mkdir(parents=True, exist_ok=True)
        _move(source, destination)
    state = {'date': release_date, 'artifacts': [path.relative_to(root).as_posix() for path in current + outputs]}
    marker.write_text(json.dumps(state, indent=2) + '\n', encoding='ascii')
    return outputs
