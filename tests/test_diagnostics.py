from pathlib import Path
from types import SimpleNamespace
import tomllib

import pytest

from command_center import cli, diagnostics, version
from command_center.paths import config_dir


@pytest.mark.parametrize("flag", ["-V", "--version"])
def test_version(flag, capsys):
    expected = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())["project"]["version"]
    assert version.FALLBACK == version.version() == expected
    with pytest.raises(SystemExit) as stopped:
        cli.main([flag])
    assert stopped.value.code == 0
    assert capsys.readouterr().out == "command-center " + expected + "\n"


def test_version_fallback(monkeypatch):
    def missing(_):
        raise version.metadata.PackageNotFoundError
    monkeypatch.setattr(version.metadata, "version", missing)
    assert version.version() == version.FALLBACK


@pytest.mark.parametrize("command", [None, *cli.COMMANDS])
def test_help(command, capsys):
    args = [command, "--help"] if command else ["-h"]
    with pytest.raises(SystemExit) as stopped:
        cli.main(args)
    assert stopped.value.code == 0
    out = capsys.readouterr()
    assert not out.err and "Kullanım:" in out.out
    if command:
        assert out.out.count("  command-center ") == 2
    else:
        for word in (*cli.COMMANDS, "--plain", "XDG_STATE_HOME", "XDG_CACHE_HOME", "XDG_CONFIG_HOME",
                     "catalog.local.toml", "config.toml", "state.json"):
            assert word in out.out


@pytest.mark.parametrize("args", [["oops"], ["check", "--oops"], ["add"], ["--ve"]])
def test_invalid_usage(args, capsys):
    with pytest.raises(SystemExit) as stopped:
        cli.main(args)
    assert stopped.value.code == 2
    out = capsys.readouterr()
    assert not out.out and "Geçersiz kullanım" in out.err


def test_offline_report(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("TERM", "term-example")
    entry = SimpleNamespace(name="example", dist=SimpleNamespace(name="example-package"),
                            load=lambda: lambda: {"title": "A", "lines": []})
    monkeypatch.setattr(cli, "discover", lambda: {"example": entry})
    monkeypatch.setattr(diagnostics, "conflicts", lambda: {"example": ["pkg-a", "pkg-b"]})
    monkeypatch.setattr(diagnostics.llm, "providers", lambda: ({"model": None}, "model"))
    config_dir().mkdir(parents=True)
    (config_dir() / "config.toml").write_text('catalog_refresh=false\nlayout=3\ntheme="bad"\nunknown=1')
    assert cli.main(["doctor"]) == 0
    out = capsys.readouterr().out
    for value in ("command-center: 0.2.0", "Python:", "Platform:", "Kurulum:", "Yorumlayıcı:",
                  "textual:", "rich:", "~/", "(var)", "(yok)", "catalog_refresh: tanındı",
                  "catalog_refresh: false", "layout: geçersiz", "theme: geçersiz", "unknown: tanınmıyor",
                  "Kaynak: çatıyla gelen liste", "example-package · OK", " ms", "pkg-a, pkg-b",
                  "Seçili model: model", "TERM: term-example", "COLORTERM:", "Terminal:"):
        assert value in out
    (config_dir() / "config.toml").write_text("[")
    assert cli.main(["doctor"]) == 0 and "okunamadı" in capsys.readouterr().out
