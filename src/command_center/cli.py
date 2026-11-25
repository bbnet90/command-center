import argparse
import sys

from . import catalog_store, state
from .config import read_order
from .plugins import discover, distribution_name, load_panel
from .rendering import line, render


def show_catalog(entries, status=None, *, mark=False, http_code=None):
    catalog = catalog_store.load_catalog()
    seen = state.read_seen(catalog.modules)
    for item in sorted(catalog.modules.values(), key=lambda m: (not m.featured, m.id)):
        label = "kurulu" if item.id in entries else "yeni" if item.id not in seen else ""
        star = "★ " if item.featured else ""
        line(f"{star}{item.id} · {item.title} · {item.kind} {label}".rstrip())
        line(f"  {item.description}")
    for row in catalog_store.footer(catalog, status, http_code):
        line(row)
    if mark:
        state.mark_seen(catalog.modules)


class Parser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, add_help=False, allow_abbrev=False, **kwargs)
        self.add_argument("-h", "--help", action="help")

    def format_help(self):
        return f"Kullanım: {self.usage}\n"

    def error(self, message):
        self.exit(2, "Geçersiz kullanım. Yardım için: command-center --help\n")


def main(argv=()) -> int:
    usages = {"llm": "", "new": "<id> [--dir PATH]", "list": "[--plain]", "catalog": "[--offline]",
              "check": "[id] [--isolated]", "add": "<id> [--yes]", "remove": "<id> [--yes]"}
    parser = Parser(prog="command-center", usage="command-center [list | catalog | add | remove | check | new | llm]")
    parser.add_argument("--plain", action="store_true")
    commands = parser.add_subparsers(dest="command")
    for name, arguments in usages.items():
        sub = commands.add_parser(name, usage=f"command-center {name} {arguments}")
        if name == "llm":
            continue
        if name == "list":
            sub.add_argument("--plain", action="store_true")
        elif name == "new":
            sub.add_argument("id")
            sub.add_argument("--dir")
        elif name == "check":
            sub.add_argument("id", nargs="?")
            sub.add_argument("--isolated", action="store_true")
        elif name == "catalog":
            sub.add_argument("--offline", action="store_true")
        else:
            sub.add_argument("id")
            sub.add_argument("--yes", action="store_true")
    args = parser.parse_args(argv)
    if args.command is None and not args.plain and sys.stdin.isatty() and sys.stdout.isatty():
        from .shell import Dashboard
        Dashboard().run()
        return 0
    if args.command == "new":
        from .scaffold import create
        return create(args.id, args.dir)
    if args.command == "llm":
        from .llm import providers
        available, selected = providers()
        if not available:
            line("Model bağlı değil")
        for key in sorted(available):
            line(f"{key} · seçili" if key == selected else key)
        return 0
    entries = discover()
    if args.command == "check":
        from .check import check
        return check(entries, args.id, isolated=args.isolated)
    if args.command == "catalog":
        result = (catalog_store.RefreshResult(catalog_store.Status.DISABLED) if args.offline
                  else catalog_store.refresh_result())
        show_catalog(entries, result.status, mark=True, http_code=result.http_code)
    elif args.command in ("add", "remove"):
        from .installer import manage
        return manage(args.command, args.id, args.yes, entries)
    elif args.command == "list":
        order = read_order()
        for key in sorted(entries):
            if args.plain:
                line(key, plain=True)
            else:
                visible = "gösteriliyor" if order is None or key in order else "gizli"
                line(f"{key} · {distribution_name(entries[key]) or '?'} · {visible}")
    elif not entries:
        print("Hiç modül yüklü değil.\n")
        show_catalog(entries)
        line("Modül kurmak için: command-center add <id>")
    else:
        order = read_order()
        if order is None:
            order = sorted(entries)
        render(load_panel(entries[key]) for key in order if key in entries)
    return 0


def entrypoint() -> int:
    return main(sys.argv[1:])
