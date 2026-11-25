import tomllib

from .paths import config_dir


def settings() -> dict:
    try:
        with (config_dir() / "config.toml").open("rb") as stream:
            return tomllib.load(stream)
    except (OSError, ValueError, RecursionError):
        return {}


def read_order() -> list[str] | None:
    panels = settings().get("panels")
    if isinstance(panels, list) and all(isinstance(item, str) for item in panels):
        return list(dict.fromkeys(panels))
    return None


def refresh_enabled() -> bool:
    return settings().get("catalog_refresh") is not False


def refresh_interval(value):
    if type(value) is not int or value == 0:
        return 0
    return max(30, min(3600, value))
