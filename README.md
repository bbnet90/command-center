# command-center

A small offline terminal dashboard for Python 3.11+. The core discovers panels
from installed packages, prints each selected panel once, and exits. Installing
or removing a plugin changes which panels are available.

Install with `pip install .` and run `command-center`. For development, install
with `pip install -e '.[dev]'` and run `pytest`.

## Plugin contract

In a separate pip package, register a zero-argument function. The entry point
name is the panel ID. For example, add this to the plugin's `pyproject.toml`:

```toml
[project.entry-points."command_center.panels"]
example = "example_plugin:panel"
```

In the plugin's `example_plugin.py`:

```python
def panel():
    return {"title": "Örnek", "lines": ["Hazır."]}
```

Return a plain dictionary with a non-empty string title and a list of text
lines. Plugins can use this contract without importing the core. A load, call,
or validation failure displays an error inside the affected panel.

## Configuration

Create `$XDG_CONFIG_HOME/command-center/config.toml` (default
`~/.config/command-center/config.toml`) to select and order panels:

```toml
panels = ["example", "another"]
```

Unknown IDs are silently skipped. An empty list selects no panels. A missing
file, missing key, or malformed configuration shows all installed panels in ID order.

## Catalog and package management

Run `command-center list` to see installed panels, their packages, and their
visibility. Use `list --plain` for one installed ID per line. With no installed
panels, the dashboard displays the offline catalog.

`command-center catalog` tries one HTTPS request before displaying the catalog.
Use `catalog --offline` for one offline lookup, or set `catalog_refresh = false`
in `config.toml` to disable all catalog requests. Other commands read local data.
The core ships a snapshot in `data/catalog.toml`. A valid cached download at
`$XDG_CACHE_HOME/command-center/catalog.toml` takes precedence. Entries in
`$XDG_CONFIG_HOME/command-center/catalog.local.toml` override either by ID.
Seen IDs live in `$XDG_STATE_HOME/command-center/state.json`. The XDG roots
default to `~/.cache`, `~/.config`, and `~/.local/state`, respectively.

Authors register their entry point as above and add a matching record to the
shared catalog or a local catalog:

```toml
format = 1

[[module]]
id = "example"
title = "Örnek"
description = "Örnek bir panel gösterir."
kind = "panel"
source = "example-plugin"
ref = "1.0.0"
```

`command-center add <id>` and `command-center remove <id>` show the exact
package-manager command and ask for confirmation. Use `--yes` for unattended
operation. Explicit installations let pip or pipx fetch third-party code and
dependencies. Removal uninstalls the owning distribution and all of its panels.
