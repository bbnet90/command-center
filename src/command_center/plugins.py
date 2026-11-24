from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from importlib import metadata
from io import StringIO
from time import perf_counter

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


def discover() -> dict[str, metadata.EntryPoint]:
    return {name: group[0] for name, group in _groups().items()}


def conflicts() -> dict[str, list[str]]:
    result = {}
    for name, group in _groups().items():
        names = list(dict.fromkeys(distribution_name(entry) or "?" for entry in group))
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


class _CapturedStream(StringIO):
    # The caller owns the captured output, even if a provider closes its stream.
    def close(self):
        pass


def inspect_panel(entry: metadata.EntryPoint) -> PanelResult:
    stdout, stderr = _CapturedStream(), _CapturedStream()
    panel = error = None
    start = perf_counter()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        try:
            provider = entry.load()
            panel = validate(provider())
        except (Exception, SystemExit) as exc:
            try:
                error = f"{type(exc).__name__}: {exc}"
            except Exception:
                error = type(exc).__name__
    return PanelResult(panel, error, stdout.getvalue(), stderr.getvalue(),
                       (perf_counter() - start) * 1000)


def load_panel(entry: metadata.EntryPoint) -> PanelData:
    result = inspect_panel(entry)
    if result.panel is None:
        return {"title": entry.name, "lines": ["Bu modüle ulaşılamadı"]}
    return result.panel
