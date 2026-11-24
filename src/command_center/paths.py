import os
from pathlib import Path


def _dir(variable: str, default: str) -> Path:
    return Path(os.environ.get(variable) or Path.home() / default) / "command-center"


def config_dir() -> Path:
    return _dir("XDG_CONFIG_HOME", ".config")


def cache_dir() -> Path:
    return _dir("XDG_CACHE_HOME", ".cache")


def state_dir() -> Path:
    return _dir("XDG_STATE_HOME", ".local/state")
