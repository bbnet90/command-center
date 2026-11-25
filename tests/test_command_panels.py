import asyncio
from contextlib import nullcontext
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
from textual.widgets import Static

from command_center.cli import main
from command_center.command_panels import CommandPanel, Processes
from command_center.contract import valid_argv
from command_center.paths import config_dir
from command_center.plugins import discover, inspect_panel, load_panel
from command_center.shell import Dashboard


def command(code):
    return CommandPanel("sample", [sys.executable, "-c", code], "Başlık", None, 1, Processes())


def configure(code, extra=""):
    config_dir().mkdir(parents=True)
    argv = json.dumps([sys.executable, "-c", code])
    (config_dir() / "config.toml").write_text(
        f'catalog_refresh=false\n[[command_panel]]\nid="sample"\ntitle="Başlık"\npanel={argv}\n{extra}'
    )


@pytest.mark.parametrize("value", [[], "command", [""], ["-arg"], [1], ["a"] * 17, ["a"*201], ["a\0"]])
def test_invalid_argv(value):
    assert not valid_argv(value)


@pytest.mark.parametrize("program,detail", [
    ("print('invalid')", "JSON"), ("raise SystemExit(2)", "çıkış kodu"),
    ("print('x'*70000)", "64 KiB"), ("import time; time.sleep(20)", "zaman aşımı"),
])
def test_command_failure(program, detail):
    assert detail in inspect_panel(command(program)).error


def test_missing_command():
    entry = command("")
    entry.argv = ["/nonexistent-panel-executable"]
    assert "FileNotFoundError" in inspect_panel(entry).error
    assert load_panel(entry)["lines"] == ["Bu modüle ulaşılamadı"]


def test_command_views(capsys):
    configure("""print('{"lines":["[red]"],"open":false}')""")
    for args, fragment in [(["--plain"], "[red]"), (["list"], "sample · komut"),
                           (["check"], "open komutu geçersiz"), (["doctor"], "sample: komut · OK")]:
        assert main(args) == 0
        assert fragment in capsys.readouterr().out


def test_isolated_command_detects_side_effect(capsys):
    configure("""from pathlib import Path;Path('new').touch();print('{"lines":[]}')""")
    assert main(["check", "sample", "--isolated"]) == 1
    assert "panel dosya oluşturdu: new" in capsys.readouterr().out


def test_collision_and_invalid_config(monkeypatch, capsys):
    configure("pass", '[[command_panel]]\nid="invalid"\npanel=["--bad"]')
    ep = SimpleNamespace(name="sample", dist=SimpleNamespace(name="dist"),
                         load=lambda: lambda: {"title": "Python", "lines": []})
    monkeypatch.setattr("importlib.metadata.entry_points",
                        lambda *, group: [ep] if group.endswith("panels") else [])
    assert discover()["sample"] is ep
    assert main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "command_panel[2]" in out and "dist, komut" in out


def test_explicit_open_and_reload(monkeypatch):
    configure("""print('{"lines":["Bir"],"open":["returned"]}')""", 'open=["configured"]')
    called = []

    async def open_runner(argv):
        called.append(argv)

    async def exercise():
        app = Dashboard(open_runner=open_runner)
        monkeypatch.setattr(app, "suspend", nullcontext)
        async with app.run_test() as pilot:
            section = app.sections[0]
            section.focus()
            for _ in range(100):
                if section.data:
                    break
                await asyncio.sleep(.02)
            assert "Enter → configured" in app.query_one("#hints", Static).content.plain
            assert not called
            await pilot.press("enter")
            assert called == [["configured"]] and section.generation == 2
    asyncio.run(exercise())


@pytest.mark.skipif(os.name != "posix", reason="POSIX process groups")
def test_timeout_kills_descendant(tmp_path):
    sentinel = tmp_path / "orphan"
    child = f"import time;from pathlib import Path;time.sleep(1.4);Path({str(sentinel)!r}).touch()"
    entry = command(f"import subprocess,sys;subprocess.Popen([sys.executable,'-c',{child!r}])")
    assert "zaman aşımı" in inspect_panel(entry).error
    import time
    time.sleep(.6)
    assert not sentinel.exists()


def test_command_stderr_is_captured():
    entry = command("""import sys;print("diagnostic",file=sys.stderr);print('{"lines":[]}')""")
    result = inspect_panel(entry)
    assert result.panel and result.stderr == "diagnostic\n"
