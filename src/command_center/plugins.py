from .capture import capture
from dataclasses import dataclass
from importlib import metadata
from time import perf_counter

from .command_panels import CommandPanel, configured
from .contract import PanelData, validate
from .distributions import normalized


def distribution_name(entry) -> str | None:
    dist = getattr(entry, "dist", None)
    return getattr(dist, "name", None)


def _sort_key(entry):
    name = distribution_name(entry) or ""
    return (not name, normalized(name), name, getattr(entry, "value", ""))


def _groups():
    groups = {}
    for entry in sorted(metadata.entry_points(group="command_center.panels"), key=_sort_key):
        groups.setdefault(entry.name, []).append(entry)
    return groups


def discover(processes=None):
    commands, _ = configured(processes)
    return {**commands, **{name: group[0] for name, group in _groups().items()}}


def package_label(entry):
    return "komut" if isinstance(entry, CommandPanel) else distribution_name(entry) or "?"


def conflicts() -> dict[str, list[str]]:
    result = {}
    commands, _ = configured()
    for name, group in _groups().items():
        names = list(dict.fromkeys(distribution_name(entry) or "?" for entry in group))
        if name in commands:
            names.append("komut")
        if len(names) > 1:
            result[name] = names
    return result


@dataclass
class PanelResult:
    panel: PanelData | None
    error: str | None
    stdout: str
    stderr: str
    elapsed_ms: float
    invalid_open: bool = False


def inspect_panel(entry: metadata.EntryPoint) -> PanelResult:
    panel = error = None
    invalid_open = False
    start = perf_counter()
    with capture("stdout") as stdout, capture("stderr") as stderr:
        try:
            provider = entry.load()
            value = provider()
            panel = validate(value)
            invalid_open = "open" in value and "open" not in panel
        except (Exception, SystemExit) as exc:
            try:
                error = f"{type(exc).__name__}: {exc}"
            except Exception:
                error = type(exc).__name__
    return PanelResult(panel, error, stdout.getvalue(), stderr.getvalue(),
                       (perf_counter() - start) * 1000, invalid_open)


def load_panel(entry: metadata.EntryPoint) -> PanelData:
    result = inspect_panel(entry)
    if result.panel is None:
        return {"title": entry.name, "lines": ["Bu modüle ulaşılamadı"]}
    return result.panel
