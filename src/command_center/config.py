import tomllib

from .paths import config_dir


def _settings() -> dict:
    try:
        with (config_dir() / "config.toml").open("rb") as stream:
            return tomllib.load(stream)
    except (OSError, ValueError, RecursionError):
        return {}


def read_order() -> list[str] | None:
    panels = _settings().get("panels")
    if isinstance(panels, list) and all(isinstance(item, str) for item in panels):
        return panels
    return None


def refresh_enabled() -> bool:
    return _settings().get("catalog_refresh") is not False
