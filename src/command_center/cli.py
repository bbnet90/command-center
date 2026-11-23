from .config import read_order
from .plugins import discover, load_panel
from .rendering import render


def main() -> None:
    entries = discover()
    if not entries:
        print("Hiç modül yüklü değil.")
        return
    order = read_order()
    if order is None:
        order = sorted(entries)
    render(load_panel(entries[key]) for key in order if key in entries)
