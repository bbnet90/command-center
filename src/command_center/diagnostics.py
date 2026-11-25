"""Offline installation and dashboard diagnostics."""
from importlib import metadata
import os
from pathlib import Path
import platform
import shutil
import sys
import tomllib

from . import catalog_store, llm
from .config import refresh_enabled
from .installer import Environment
from .paths import cache_dir, config_dir, state_dir
from .plugins import conflicts, package_label, inspect_panel
from .text import clean
from .version import version


def paths():
    return {
        "Yapılandırma": config_dir() / "config.toml",
        "Durum": state_dir() / "state.json",
        "Önbellek": cache_dir() / "catalog.toml",
        "Yerel katalog": config_dir() / "catalog.local.toml",
    }


def display(path):
    path = Path(path)
    return str(Path("~") / path.relative_to(Path.home())) if path.is_relative_to(Path.home()) else str(path)


def report(entries):
    def row(label, value):
        print(clean(f"{label}: {value}"))

    env = Environment.current()
    mode = ("pipx" if env.uses_pipx else "venv" if env.prefix != env.base_prefix
            else "dışarıdan yönetilen sistem" if env.managed else "sistem")
    row("command-center", version())
    row("Python", platform.python_version())
    row("Platform", platform.platform())
    row("Kurulum", mode)
    row("Yorumlayıcı", display(sys.executable))
    for package in ("textual", "rich"):
        row(package, metadata.version(package))
    for name, path in paths().items():
        row(name, f"{display(path)} ({'var' if path.exists() else 'yok'})")
    from .command_panels import configured
    _, errors = configured()
    for error in errors:
        row("Komut paneli", error)
    validators = {
        "command_panel": lambda v: not errors,
        "panels": lambda v: isinstance(v, list) and all(isinstance(x, str) for x in v),
        "catalog_refresh": lambda v: isinstance(v, bool),
        "layout": lambda v: v in ("single", "two-column"),
        "theme": valid_theme,
        "llm": lambda v: isinstance(v, str) and bool(v),
    }
    try:
        with (config_dir() / "config.toml").open("rb") as stream:
            config = tomllib.load(stream)
    except FileNotFoundError:
        config = {}
    except (OSError, ValueError, RecursionError):
        config = {}
        row("config.toml", "geçersiz veya okunamadı")
    for key, value in config.items():
        row(key, ("tanınmıyor" if key not in validators else
                  "tanındı" if validators[key](value) else "geçersiz"))
    catalog = catalog_store.load_catalog()
    for source in catalog_store.footer(catalog):
        print(source)
    row("catalog_refresh", str(refresh_enabled()).lower())
    row("Paneller", len(entries))
    for name, entry in sorted(entries.items()):
        result = inspect_panel(entry)
        row(name, f"{package_label(entry)} · {'FAIL' if result.error else 'OK'} · {result.elapsed_ms:.2f} ms")
    duplicates = conflicts()
    row("Giriş noktası çakışmaları", len(duplicates))
    for key, names in sorted(duplicates.items()):
        row(key, ", ".join(names))
    available, selected = llm.providers()
    row("Model sağlayıcıları", ", ".join(sorted(available)) or "yok")
    row("Seçili model", selected or "yok")
    for key in ("TERM", "COLORTERM"):
        row(key, os.environ.get(key) or "belirtilmedi")
    size = shutil.get_terminal_size()
    row("Terminal", f"{size.columns} × {size.lines}")
    return 0


def valid_theme(name):
    from textual.theme import BUILTIN_THEMES
    return isinstance(name, str) and name in BUILTIN_THEMES
