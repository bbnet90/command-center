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
