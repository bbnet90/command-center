# command-center

[Hızlı başlangıç (Türkçe)](README.tr.md)

Command Center is a local-first terminal dashboard for Python 3.11+. Installed
Python packages and configured commands supply independent panels. A slow panel
loads in the background. A failed refresh keeps its last successful snapshot.

## Installation and first run

With pipx and Git installed, run:

```sh
pipx install git+https://github.com/bbnet90/command-center.git
command-center
```

For a checkout of this version, run `pipx install .` from the repository.
A terminal opens the dashboard. With no panels the catalog opens automatically:
select a panel, press Enter to inspect the source and installation command,
then press y to confirm. A verified panel appears immediately. Redirected
input or output and `command-center --plain` select the static snapshot.

## Dashboard keys

| Key | Action |
| --- | --- |
| Tab / Shift+Tab | Focus the question input or next/previous panel |
| ↑ ↓ / PageUp PageDown | Scroll inside the focused panel |
| r / R | Refresh the focused panel / all panels |
| [ / ] | Move the focused panel earlier / later |
| Enter | Open the focused panel's optional program, or submit a question in the input |
| l / t | Cycle the layout / built-in theme |
| m | Open the module catalog; Enter previews installation, x previews removal |
| y | Confirm the displayed package operation |
| Esc | Dismiss the modal or discard a pending model answer |
| ? | Show keyboard help |
| q / Ctrl+C | Quit (q outside text input); confirm if a package process is active |

Two-column layout activates at 100 terminal columns. Narrower terminals keep
the saved preference and display one column. Panel borders show the last
successful update time. After ten seconds the dashboard flags a slow panel
and continues to accept a late result.

## Optional question provider

Register a callable in a separate installed package:

```toml
[project.entry-points."command_center.llm"]
example = "example_provider:answer"
```

`answer(question: str, context: str) -> str` receives up to 500 question
characters and 4000 characters of loaded panel titles and lines. Return plain
text. The UI limits answers to 2000 characters. Escape discards a pending
answer. Set `llm = "example"` to select a provider, or use the first installed
ID alphabetically. Run `command-center llm` to inspect the selection.
The distribution ships without a provider.

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
lines. An optional `open` argument list enables an explicit terminal action. Plugins can use this contract without importing the core. A load, call,
or validation failure displays an error inside the affected panel.

## Configuration

Create `$XDG_CONFIG_HOME/command-center/config.toml` (default
`~/.config/command-center/config.toml`) to select and order panels:

```toml
panels = ["example", "another"]
```

| Optional key | Meaning |
| --- | --- |
| panels | Visible panel IDs in preferred order |
| catalog_refresh | Boolean, defaults to true; false disables catalog requests |
| refresh_seconds | Automatic panel refresh interval. Missing or zero disables it; other integers clamp to 30–3600 seconds. Modals pause refreshes and active loads are skipped. |
| layout | single (default) or two-column |
| theme | Built-in Textual theme name; unknown names fall back to the built-in default |
| llm | Preferred installed provider ID |
| command_panel | Array of local command definitions (see below) |

The state file stores `seen` catalog IDs and the dashboard's `order`, `layout`
and `theme`. Saved choices override config defaults. Known saved order IDs
come first, followed by other visible panels in configured or alphabetical
order. Writes are atomic. A corrupt state file is treated as missing.

Unknown IDs are silently skipped. An empty list selects no panels. A missing
file, missing key, or malformed configuration shows all installed panels in ID order.

## Catalog and package management

Run `command-center list` to see installed panels, their packages, and their
visibility. Use `list --plain` for one installed ID per line. With no installed
panels, the dashboard displays the offline catalog.

`command-center catalog` tries one HTTPS request before displaying the catalog.
Use `catalog --offline` for one offline lookup, or set `catalog_refresh = false`
in `config.toml` to disable all catalog requests. Opening the interactive module catalog also requests a refresh unless disabled.
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

## Writing a module

Run `command-center new example` to create a standalone package. Use
`--dir PATH` to choose a different destination. Keep the provider **read-only**,
**fast**, and **silent** (never print). Install the package in the same Python
environment as the dashboard with `pip install -e .`. Run `command-center check`
to inspect all installed panels, or `command-center check example --isolated`
to inspect one in a fresh process with an empty home and XDG directories.
Width, captured output, and duplicate entry point names produce warnings.
Provider exceptions, invalid return values, or files left in the temporary
directory fail the check. The filesystem check only sees paths left there at
exit. Databases in a source checkout or selected by module-specific environment
variables outside HOME are outside its scope.

After publishing the package, paste the generated `[[module]]` entry into the
catalog and edit its title, description, and published source. The ID must match
the entry point. See the catalog example above.

**Contract stability.** Changes are additive. The core reads `title`, `lines` and optional `open`
and ignores extra keys. It displays at most 100 lines of 300 characters each,
reserving the final line for a truncation notice whenever content is clipped.

## Non-Python modules

Command panels are local programs configured by the user. The shell discovers
these alongside Python entry points. Python wins when both use the same ID.
For example, install a version of the Todo CLI supporting `panel --json`,
put its executable on PATH, then add this to command-center's config.toml:

```toml
[[command_panel]]
id = "todo"
title = "Yapılacaklar"
panel = ["todo", "panel", "--json"]
open = ["todo"]
timeout = 10
```

The dashboard runs the argument list directly from the home directory, with
stdin closed. Return one UTF-8 JSON document on stdout, for example
`{"title":"Yapılacaklar","lines":["Görev yok."],"open":["todo"]}`.
The limit is 64 KiB and the timeout is 1–30 seconds. Each panel loads
independently. `check` reports errors and `doctor` lists configuration issues.
The optional open command (explicit configuration takes precedence) runs only
on Enter in the focused panel. The dashboard lends it the terminal and
refreshes the panel when it returns. Only configure trusted programs.


## Trust and troubleshooting

The catalog is the trust root for installation sources. Review the source,
revision and exact package command before confirming an install. A missing
revision allows upstream changes. Python panels execute in the dashboard
process with your account permissions. Command panels run as your user too.
Timeouts and output limits bound execution and display; providers can still
access local files. Only install packages and configure commands you trust.

Run `command-center doctor` for an offline report of paths, recognized config,
terminal, catalog and installed panel checks. It calls each installed provider.
Use `command-center check <id>` for errors, or `command-center list` to inspect
visibility. For a missing external command, verify PATH in the terminal
launching the dashboard. For development, run `pip install -e '.[dev]'`
and `python -m pytest`.
