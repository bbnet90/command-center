from importlib import metadata

from .capture import capture
from .config import settings
from .text import clean


def providers():
    entries = {ep.name: ep for ep in metadata.entry_points(group="command_center.llm")}
    choice = settings().get("llm")
    selected = choice if isinstance(choice, str) and choice in entries else min(entries, default=None)
    return entries, selected


def context(panels):
    return "\n".join(row for panel in panels for row in (panel["title"], *panel["lines"]))[:4000]


def answer(entry, question, panel_context):
    with capture("stdout"), capture("stderr"):
        try:
            raw = entry.load()(question[:500], panel_context[:4000])
            if not isinstance(raw, str):
                return "Model yanıt vermedi"
            response = clean(raw)
        except (Exception, SystemExit):
            return "Model yanıt vermedi"
    suffix = "… (kısaltıldı)"
    return response if len(response) <= 2000 else response[:2000 - len(suffix)] + suffix
