from importlib import metadata
from types import SimpleNamespace

import pytest

from command_center.cli import main
from command_center.rendering import PANEL_WIDTH


@pytest.fixture
def config_path(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    path = tmp_path / "command-center" / "config.toml"
    path.parent.mkdir()
    return path


@pytest.fixture
def run(monkeypatch, config_path, capsys):
    def invoke(*entries):
        def discover(*, group):
            assert group == "command_center.panels"
            return entries

        monkeypatch.setattr(metadata, "entry_points", discover)
        main()
        result = capsys.readouterr()
        assert result.err == ""
        return result.out

    return invoke


def entry(name, provider=None):
    if provider is None:
        def provider():
            return {"title": name.upper(), "lines": []}
    return SimpleNamespace(name=name, load=lambda: provider)


def test_no_plugins(run):
    output = run()
    assert output.startswith("Hiç modül yüklü değil.\n\n")
    assert "Evdeki Eşyalar" in output
    assert output.endswith("Modül kurmak için: command-center add <id>\n")


def test_valid_plugin(run):
    def panel():
        return {"title": "[bold]Başlık", "lines": ["Bir", "[red]İki"]}

    top, first, second, bottom = run(entry("a", panel)).splitlines()
    assert top.startswith("╭") and top.endswith("╮") and "[bold]Başlık" in top
    assert "Bir" in first and "[red]İki" in second
    assert bottom.startswith("╰") and bottom.endswith("╯")
    assert all(len(row) == PANEL_WIDTH for row in (top, first, second, bottom))


@pytest.mark.parametrize("stage", ["load", "call"])
def test_plugin_failure(run, stage):
    def fail():
        raise RuntimeError("private details")

    broken = SimpleNamespace(name="broken", load=fail) if stage == "load" else entry("broken", fail)
    output = run(broken, entry("ok"))
    assert "broken" in output and "Bu modüle ulaşılamadı" in output
    assert "private details" not in output and "OK" in output


@pytest.mark.parametrize("data", [
    None, {}, {"title": "", "lines": []}, {"title": " ", "lines": []},
    {"title": 1, "lines": []}, {"title": "A", "lines": "bad"},
    {"title": "A", "lines": [1]},
])
def test_invalid_result(run, data):
    output = run(entry("broken", lambda: data))
    assert "broken" in output and "Bu modüle ulaşılamadı" in output


@pytest.mark.parametrize("config", [None, "", "panels = [", 'panels = "b"', "panels = [1]"])
def test_default_order(run, config_path, config):
    if config is not None:
        config_path.write_text(config)
    output = run(entry("b"), entry("a"))
    assert output.index("A") < output.index("B")


def test_config_order(run, config_path):
    config_path.write_text('panels = ["b", "missing", "a"]')
    hidden = SimpleNamespace(name="c", load=lambda: pytest.fail("Hidden panel loaded"))
    output = run(entry("a"), hidden, entry("b"))
    assert output.index("B") < output.index("A")
    assert "missing" not in output and output.count("╭") == 2


@pytest.mark.parametrize("selection", ["[]", '["missing"]'])
def test_empty_selection(run, config_path, selection):
    config_path.write_text(f"panels = {selection}")
    assert run(entry("a")) == ""


def test_home_fallback(run, tmp_path, monkeypatch):
    monkeypatch.delenv("XDG_CONFIG_HOME")
    monkeypatch.setenv("HOME", str(tmp_path))
    path = tmp_path / ".config" / "command-center" / "config.toml"
    path.parent.mkdir(parents=True)
    path.write_text('panels = ["b"]')
    output = run(entry("a"), entry("b"))
    assert "B" in output and "A" not in output
