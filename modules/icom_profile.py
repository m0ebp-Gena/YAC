"""Load model capabilities and CI-V command bytes from rad_cmds."""

import json
from functools import lru_cache
from pathlib import Path


SUPPORTED_MODELS = frozenset({"ic-705", "ic-7300", "ic-7300mk2"})


@lru_cache(maxsize=8)
def load_profile(root: Path, model: str) -> dict:
    directory = root / "rad_cmds" / "icom" / "CI-V" / "models" / model.casefold()
    profile = json.loads((directory / "profile.json").read_text(encoding="utf-8"))
    profile["modes"] = {int(code, 16): label for code, label in profile["modes"].items()}
    profile["commands"] = {
        group: {
            name: bytes.fromhex((directory / group / name).read_text(encoding="ascii"))
            for name in names
        }
        for group, names in profile["command_files"].items()
    }
    return profile
