import asyncio
from importlib import metadata
from threading import Event
from types import SimpleNamespace

import pytest
from textual.widgets import Input, OptionList, RichLog, Static

from command_center import catalog_store, llm, state
from command_center.catalog import Module
from command_center.catalog_screen import CatalogScreen, Confirmation
from command_center.cli import main
from command_center.installer import Environment
from command_center.paths import config_dir, state_dir
from command_center.rendering import PANEL_WIDTH, render
from command_center.shell import Dashboard, Section


def entry(name, function):
    return SimpleNamespace(name=name, load=lambda: function, dist=SimpleNamespace(name="demo-pkg"))


def panel(name):
    return entry(name, lambda: {"title": "[red]" + name, "lines": ["長"*300]*100})


def setup(monkeypatch, panels, providers=()):
    groups = {"command_center.panels": panels, "command_center.llm": providers}
    monkeypatch.setattr(metadata, "entry_points", lambda *, group: groups[group])
    config_dir().mkdir(parents=True)
    (config_dir() / "config.toml").write_text("catalog_refresh=false")


async def until(predicate):
    for _ in range(100):
        if predicate():
            return
        await asyncio.sleep(.02)
    assert predicate()


def test_parallel_and_clipping(monkeypatch, capsys):
    gate = Event()

    def slow():
        gate.wait(5)
        print("captured")
        return {"title": "Done", "lines": ["ready"]}

    setup(monkeypatch, [entry("a", slow), panel("b"), entry("c", lambda: 1/0)])

    async def exercise():
        app = Dashboard()
        async with app.run_test(size=(82, 34)) as pilot:
            try:
                a, b, c = app.sections
                await until(lambda: b.data and c.data)
                assert a.rows == ["yükleniyor…"] and c.rows == ["Bu modüle ulaşılamadı"]
                a.slow(a.generation)
                assert a.rows == ["yanıt vermiyor…"]
                await pilot.pause()
                text = b.query_one(Static).content
                assert len(text.plain.splitlines()) == 100
                assert all(row.endswith("…") for row in text.plain.splitlines())
                assert app.query_one(Input).disabled
            finally:
                gate.set()
            await until(lambda: a.caption == "Done")
    asyncio.run(exercise())
    render([panel("p").load()()])
    rows = capsys.readouterr().out.splitlines()
    assert len(rows) == 102 and all(len(row) <= PANEL_WIDTH for row in rows)


def test_focus_order_layout_and_theme(monkeypatch):
    setup(monkeypatch, [panel("a"), panel("b")], [entry("model", lambda *_: "OK")])
    (config_dir() / "config.toml").write_text('layout="two-column"\ntheme="unknown"')
    state_dir().mkdir(parents=True)
    (state_dir() / "state.json").write_text("bad json")
    state.mark_seen(["demo"])

    async def exercise():
        app = Dashboard()
        async with app.run_test(size=(80, 30)) as p:
            assert app.focused is app.query_one(Input)
            assert app.theme == "textual-dark" and app.preset == "two-column"
            grid = app.query_one("#sections")
            assert not grid.has_class("wide")
            await p.resize_terminal(110, 30)
            await until(lambda: grid.has_class("wide"))
            await p.press("tab")
            assert app.focused is app.sections[0]
            await p.press("right_square_bracket")
            assert [s.key for s in app.sections] == ["b", "a"]
            await p.press("l", "t")
            assert not grid.has_class("wide")
            assert app.theme != "textual-dark"
            await p.press("shift+tab")
            assert app.focused is app.sections[0]
        saved = Dashboard()
        assert [s.key for s in saved.sections] == ["b", "a"]
        assert saved.preset == "single" and saved.theme == app.theme
        assert state.read_seen([]) == {"demo"}
    asyncio.run(exercise())


def test_llm(monkeypatch, capsys):
    gate = Event()
    calls = []

    def provider(q, ctx):
        calls.append((q, ctx))
        if q == "wait":
            gate.wait(3)
        if q == "error":
            raise ValueError
        return "[red]" + "ğ"*2200

    setup(monkeypatch, [panel("visible")], [entry("z", provider), entry("a", provider)])
    assert main(["llm"]) == 0 and "a · seçili" in capsys.readouterr().out
    (config_dir() / "config.toml").write_text('llm="z"')
    assert llm.providers()[1] == "z"

    async def exercise():
        app = Dashboard()
        async with app.run_test() as p:
            field = app.query_one(Input)
            output = app.query_one("#answer", Static)
            await until(lambda: app.sections[0].data)
            field.value = "a"*500
            await p.press("enter")
            await until(lambda: output.content.plain.endswith("… (kısaltıldı)"))
            assert len(output.content.plain) == 2000 and output.content.plain.startswith("[red]")
            assert len(calls[0][0]) == 500 and len(calls[0][1]) == 4000
            assert calls[0][1].startswith("[red]visible")
            field.value = "wait"
            await p.press("enter", "escape")
            gate.set()
            await p.pause()
            assert output.content.plain == ""
            field.value = "error"
            await p.press("enter")
            await until(lambda: output.content.plain == "Model yanıt vermedi")
    asyncio.run(exercise())


@pytest.fixture
def install_venv(tmp_path, monkeypatch):
    prefix = tmp_path / "venv"
    env = Environment(prefix, tmp_path, str(prefix / "python"), pipx=False, managed=False)
    monkeypatch.setattr(Environment, "current", lambda: env)


def test_catalog_flow(monkeypatch, install_venv):
    installed = []
    setup(monkeypatch, installed)
    item = Module("demo", "[red] Başlık", "Tanım", "panel", "demo-pkg", featured=True)
    monkeypatch.setattr(catalog_store, "load_catalog", lambda: catalog_store.Catalog({"demo": item}, None))
    state.mark_seen([])
    calls = []

    def run(argv, emit, **kwargs):
        calls.append(argv)
        if kwargs.get("capture_output"):
            return SimpleNamespace(returncode=0, stdout="\n".join(ep.name for ep in installed))
        emit("canlı çıktı")
        if "install" in argv:
            installed.append(panel("demo"))
        else:
            installed.clear()
        return SimpleNamespace(returncode=0)

    async def exercise():
        app = Dashboard(runner=run)
        async with app.run_test() as p:
            await until(lambda: isinstance(app.screen, CatalogScreen))
            modal = app.screen
            await p.pause()
            assert modal.result.status == catalog_store.Status.DISABLED
            assert "yeni" in modal.query_one(OptionList).get_option_at_index(0).prompt.plain
            await p.press("enter")
            await until(lambda: isinstance(app.screen, Confirmation))
            await p.press("n")
            await until(lambda: not modal.busy)
            assert not calls
            await p.press("enter", "y")
            await until(lambda: len(app.sections) == 1 and not modal.busy)
            assert any("canlı çıktı" in strip.text for strip in modal.query_one(RichLog).lines)
            await p.press("x", "y")
            await until(lambda: not app.sections and not modal.busy)
            await p.press("escape")
            assert app.screen is app.base_screen
            assert state.read_seen([]) == {"demo"}
    asyncio.run(exercise())


def test_plain_and_terminal_dispatch(monkeypatch, capsys):
    import sys

    setup(monkeypatch, [panel("a")])
    launched = []
    monkeypatch.setattr(Dashboard, "run", lambda self: launched.append(self))
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    assert main([]) == 0 and len(launched) == 1
    assert main(["--plain"]) == 0 and "╭" in capsys.readouterr().out
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    assert main([]) == 0 and "╭" in capsys.readouterr().out and len(launched) == 1


def test_refresh_and_scroll(monkeypatch):
    calls = []

    def provider():
        calls.append("a")
        return {"title": "A", "lines": ["uzun"]*100}

    setup(monkeypatch, [entry("a", provider), panel("b")])

    async def exercise():
        app = Dashboard()
        async with app.run_test() as p:
            await until(lambda: all(s.data for s in app.sections))
            s = app.sections[0]
            s.focus()
            await p.pause()
            await until(lambda: s.max_scroll_y > 0)
            await p.press("pagedown")
            await until(lambda: s.scroll_y > 0)
            await p.press("pageup", "r", "R")
            await until(lambda: len(calls) == 3)
            assert app.sections[1].generation == 2
    asyncio.run(exercise())


def test_catalog_failed_verification(monkeypatch, install_venv):
    setup(monkeypatch, [])
    item = Module("demo", "Deneme", "Açıklama", "panel", "demo-pkg", ref="1")
    monkeypatch.setattr(catalog_store, "load_catalog", lambda: catalog_store.Catalog({"demo": item}, 1))

    def run(argv, **kwargs):
        name = "demo-pkg\n" if "command_center.distributions" in argv else ""
        return SimpleNamespace(returncode=0, stdout=name)

    async def exercise():
        app = Dashboard(runner=run)
        async with app.run_test(size=(120, 30)) as p:
            await until(lambda: isinstance(app.screen, CatalogScreen))
            await p.pause()
            modal = app.screen
            await p.press("enter")
            await until(lambda: isinstance(app.screen, Confirmation))
            assert "Bu işlem üçüncü taraf kod kurar." in app.screen.rows
            assert any("demo-pkg==1" in row for row in app.screen.rows)
            await p.press("y")
            await until(lambda: not modal.busy)
            output = "\n".join(row.text for row in modal.query_one(RichLog).lines)
            assert "Kaldırmak için:" in output and "uninstall -y demo-pkg" in output
            assert "command_center.panels giriş noktası" in output and not app.sections
    asyncio.run(exercise())


def test_overlapping_capture_keeps_streams_separate():
    from concurrent.futures import ThreadPoolExecutor
    import sys

    from command_center.plugins import inspect_panel

    started, overlap, release = Event(), Event(), Event()
    originals = sys.stdout, sys.stderr

    def first():
        print("first")
        started.set()
        assert overlap.wait(3)
        print("first-end", file=sys.stderr)
        return {"title": "A", "lines": []}

    def second():
        assert started.wait(3)
        print("second", file=sys.stderr)
        overlap.set()
        assert release.wait(3)
        print("second-end")
        return {"title": "B", "lines": []}

    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(inspect_panel, entry("a", first))
        assert started.wait(3)
        b = pool.submit(inspect_panel, entry("b", second))
        try:
            first_result = a.result(3)
        finally:
            release.set()
        second_result = b.result(3)
    assert (sys.stdout, sys.stderr) == originals
    assert (first_result.stdout, first_result.stderr) == ("first\n", "first-end\n")
    assert (second_result.stdout, second_result.stderr) == ("second-end\n", "second\n")


def test_answer_contract_limits():
    received = []

    def respond(q, ctx):
        received.append((q, ctx))
        print("discard")
        return "\u202e[red]"

    assert llm.answer(entry("test", respond), "q"*501, "a"*4001) == "[red]"
    assert received == [("q"*500, "a"*4000)]
    assert llm.answer(entry("test", lambda *_: []), "", "") == "Model yanıt vermedi"


def test_quit_during_package_process(monkeypatch):
    import sys

    setup(monkeypatch, [panel("a")])

    async def exercise():
        app = Dashboard()
        async with app.run_test() as pilot:
            child = asyncio.create_task(asyncio.to_thread(
                app.packages.run, [sys.executable, "-c", "import time; time.sleep(120)"],
                cwd=None, emit=lambda _: None,
            ))
            try:
                await until(lambda: app.packages.child is not None)
                await pilot.press("q")
                assert isinstance(app.screen, Confirmation)
                assert app.screen.prompt == "Kurulum sürüyor, çıkılsın mı? (y/n)"
                await pilot.press("n")
                assert not child.done()
                await pilot.press("q", "y")
                assert (await asyncio.wait_for(child, 4)).returncode != 0
            finally:
                await app.packages.shutdown()
    asyncio.run(exercise())


@pytest.mark.parametrize("size", [(40, 24), (50, 30), (80, 40), (120, 40)])
def test_responsive_panels_and_help(monkeypatch, size):
    from rich.cells import cell_len
    from command_center.shell import HINTS, KeyHelp

    setup(monkeypatch, [panel("a"), panel("b")])

    async def exercise():
        app = Dashboard()
        async with app.run_test(size=size) as pilot:
            await until(lambda: all(section.data for section in app.sections))
            await pilot.pause()
            for section in app.sections:
                assert app.screen.region.contains_region(section.region)
                assert section.max_scroll_y > 0
                assert all(cell_len(row) <= section.scrollable_content_region.width
                           for row in section.query_one(Static).content.plain.splitlines())
                assert "güncellendi" in section.border_subtitle
            section.focus()
            for theme in ("textual-light", "textual-dark", "nord"):
                app.theme = theme
                await pilot.pause()
                assert app.focused is section, (app.focused, section.has_focus, theme)
                assert "❯" in section.border_title
                assert section.styles.border != app.sections[0].styles.border
            hint = app.query_one("#hints").content.plain
            assert ("Tab odak" in hint) == (size[0] >= cell_len(HINTS))
            await pilot.press("question_mark")
            assert isinstance(app.screen, KeyHelp)
            await pilot.press("escape")
            assert app.screen is app.base_screen
    asyncio.run(exercise())


def test_failed_refresh_preserves_last_success(monkeypatch):
    values = iter([{"title": "A", "lines": ["sonuç"]}, None])
    setup(monkeypatch, [entry("a", lambda: next(values))])

    async def exercise():
        app = Dashboard()
        async with app.run_test():
            section = app.sections[0]
            await until(lambda: section.last_success)
            section.reload()
            await until(lambda: section.unresponsive)
            assert section.rows == ["sonuç"] and section.has_class("stale")
            assert section.border_subtitle == f"eski veri · {section.last_success}"
            assert "1 panel yanıt vermiyor" in app.query_one("#greeting").content.plain
    asyncio.run(exercise())


@pytest.mark.parametrize(("value", "interval"), [(None, 0), (0, 0), (True, 0), ("30", 0),
                                                  (-1, 30), (1, 30), (80, 80), (7200, 3600)])
def test_auto_interval(value, interval):
    from command_center.config import refresh_interval
    assert refresh_interval(value) == interval


def test_auto_refresh_ticks(monkeypatch):
    gate = Event()
    setup(monkeypatch, [entry("a", lambda: gate.wait(5)), panel("b")])
    (config_dir() / "config.toml").write_text("refresh_seconds=31\ncatalog_refresh=false")

    async def exercise():
        app = Dashboard()
        schedule = {}
        original = app.set_interval

        def clock(seconds, callback, **kwargs):
            if seconds == 31:
                schedule[seconds] = callback
                return
            return original(seconds, callback, **kwargs)
        monkeypatch.setattr(app, "set_interval", clock)
        async with app.run_test() as pilot:
            try:
                a, b = app.sections
                await until(lambda: b.data)
                tick = schedule[31]
                tick()
                tick()
                assert (a.generation, b.generation) == (1, 2)
                await until(lambda: not b.in_flight)
                await pilot.press("question_mark")
                tick()
                assert b.generation == 2
                await pilot.press("escape")
                tick()
                assert b.generation == 3
            finally:
                gate.set()
    asyncio.run(exercise())
