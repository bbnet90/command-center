from importlib import metadata

from .contract import PanelData, validate


def discover() -> dict[str, metadata.EntryPoint]:
    entries = metadata.entry_points(group="command_center.panels")
    return {entry.name: entry for entry in entries}


def load_panel(entry: metadata.EntryPoint) -> PanelData:
    try:
        provider = entry.load()
        return validate(provider())
    except (Exception, SystemExit):
        return {"title": entry.name, "lines": ["Bu modüle ulaşılamadı"]}
