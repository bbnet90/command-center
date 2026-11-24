from collections.abc import Iterable

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from .text import clean
from .contract import PanelData

PANEL_WIDTH = 50


def render(panels: Iterable[PanelData]) -> None:
    console = Console(width=PANEL_WIDTH)
    for panel in panels:
        console.print(Panel(
            Text("\n".join(panel["lines"])),
            title=Text(clean(panel["title"])),
            box=box.ROUNDED,
        ))


def line(value: str, *, plain=False) -> None:
    Console().print(Text(clean(value)), soft_wrap=plain)
