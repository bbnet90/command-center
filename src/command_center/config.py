import os
from pathlib import Path
import tomllib


def read_order() -> list[str] | None:
    root = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    path = Path(root) / "command-center" / "config.toml"
    try:
        with path.open("rb") as stream:
            panels = tomllib.load(stream).get("panels")
    except (OSError, ValueError, RecursionError):
        return None
    if isinstance(panels, list) and all(isinstance(item, str) for item in panels):
        return panels
    return None
