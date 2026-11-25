from dataclasses import replace
from importlib import metadata
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

from command_center import catalog_store, installer, state
from command_center.catalog import Module
from command_center.cli import main
from command_center.installer import Environment, build_spec, manage, plan
from command_center.paths import config_dir

ITEM = Module("alpha", "Alpha", "Example", "panel", "alpha-pkg")
ENV = Environment(Path("/venv"), Path("/sys"), "/venv/bin/python", False, True)


def test_plan():
    assert plan(ENV, module=ITEM).argv == [ENV.executable, "-m", "pip", "install", ITEM.source]
    system = replace(ENV, prefix=ENV.base_prefix, managed=False)
    assert plan(system, module=ITEM).argv[-3:] == ["install", "--user", ITEM.source]
    assert plan(system, dist="abc").argv[-3:] == ["uninstall", "-y", "abc"]
    protected = replace(system, managed=True)
    assert plan(protected, module=ITEM).blocked and plan(protected, dist="abc").blocked
    pipx = replace(ENV, prefix=Path("/pipx/venvs/command-center"), pipx=True)
    assert plan(pipx, module=ITEM).argv == ["pipx", "inject", "command-center", ITEM.source]
    assert plan(pipx, dist="abc").argv == ["pipx", "runpip", "command-center", "uninstall", "-y", "abc"]
    assert build_spec(replace(ITEM, ref="1.2")) == "alpha-pkg==1.2"
    url = "git+https://host/repo"
    assert build_spec(replace(ITEM, source=url, ref="v1")) == url + "@v1"
    for bad in (replace(ITEM, ref="-x"), replace(ITEM, source="--user")):
        with pytest.raises(ValueError):
            plan(ENV, module=bad)
    with pytest.raises(ValueError):
        plan(ENV, dist="--user")


def entry(name, dist=None):
    return SimpleNamespace(name=name, dist=SimpleNamespace(name=dist))


@pytest.fixture
def catalog(monkeypatch):
    modules = {"alpha": ITEM, "beta": replace(ITEM, id="beta", kind="command", featured=True)}
    data = catalog_store.Catalog(modules, 3)
    monkeypatch.setattr(catalog_store, "load_catalog", lambda: data)
    monkeypatch.setattr(installer, "load_catalog", lambda: data)
    return data


def test_lists(catalog, monkeypatch, capsys):
    monkeypatch.setattr(metadata, "entry_points", lambda **kw: [entry("alpha"), entry("z", "pkg")])
    config_dir().mkdir(parents=True)
    (config_dir() / "config.toml").write_text('panels=["alpha"]')
    assert main(["list", "--plain"]) == 0
    assert capsys.readouterr().out == "alpha\nz\n"
    main(["list"])
    output = capsys.readouterr().out
    assert "alpha · ? · gösteriliyor" in output and "z · pkg · gizli" in output
    monkeypatch.setattr(catalog_store, "refresh_result", lambda: pytest.fail("network"))
    state.mark_seen({"alpha"})
    main(["catalog", "--offline"])
    out = capsys.readouterr().out
    assert out.index("★ beta") < out.index("alpha")
    assert "yeni" in out and "kurulu" in out and "önbellek (3 gün önce)" in out
    main(["catalog", "--offline"])
    assert "yeni" not in capsys.readouterr().out
    for status, expected in [(catalog_store.Status.UPDATED, "Kaynak: güncel indirme"),
                             (catalog_store.Status.OFFLINE, "Çevrimdışı: yenilenemedi")]:
        monkeypatch.setattr(catalog_store, "refresh_result", lambda: catalog_store.RefreshResult(status))
        main(["catalog"])
        assert expected in capsys.readouterr().out


@pytest.mark.parametrize(("key", "entries", "yes", "tty", "rc", "message"), [
    ("alpha", {}, False, True, 0, "iptal"),
    ("alpha", {}, False, False, 1, "--yes"),
    ("alpha", {"alpha": entry("alpha")}, True, False, 0, "zaten"),
    ("alph", {}, True, False, 1, "Benzer kimlikler: alpha"),
    ("beta", {}, True, True, 1, "Bu tür henüz desteklenmiyor"),
])
def test_no_execution(catalog, monkeypatch, capsys, key, entries, yes, tty, rc, message):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: tty)
    monkeypatch.setattr("builtins.input", lambda _: "")
    assert manage("add", key, yes, entries, env=ENV, runner=lambda *a, **kw: pytest.fail()) == rc
    assert message in capsys.readouterr().out


@pytest.mark.parametrize(("action", "plain", "rc"), [
    ("add", "alpha\n", 0), ("add", "", 1), ("remove", "", 0), ("remove", "other\n", 1),
])
def test_execution(catalog, capsys, action, plain, rc):
    entries = {} if action == "add" else {"alpha": entry("alpha", "Pkg-A"), "other": entry("other", "pkg_a")}
    calls = []

    def runner(argv, **kw):
        calls.append(argv)
        return SimpleNamespace(returncode=0, stdout=plain)

    assert manage(action, "alpha", True, entries, env=ENV, runner=runner) == rc
    assert calls[1] == [ENV.executable, "-m", "command_center", "list", "--plain"]
    out = capsys.readouterr().out
    if action == "add":
        assert "sürüme sabitlenmemiş" in out and "Bu işlem üçüncü taraf kod kurar." in out
        assert ("Kuruldu ve bağlandı." if rc == 0 else "panel kaydı bulunamadı") in out
    else:
        assert calls[0][-3:] == ["uninstall", "-y", "Pkg-A"]
        assert "alpha, other" in out and "Dikkat" in out


def test_no_abbreviated_confirmation():
    with pytest.raises(SystemExit) as caught:
        main(["add", "alpha", "--y"])
    assert caught.value.code == 2


def test_protected_environment_and_ordinary_venvs(catalog, capsys):
    protected = replace(ENV, prefix=ENV.base_prefix)
    assert manage("add", "alpha", True, {}, env=protected,
                  runner=lambda *a, **kw: pytest.fail()) == 1
    assert "pipx inject command-center alpha-pkg" in capsys.readouterr().out
    ordinary = replace(ENV, prefix=Path("/projects/venvs/test"), pipx=True)
    assert plan(ordinary, module=ITEM).argv[0] == ENV.executable


def test_interrupt(catalog, capsys):
    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt()

    assert manage("add", "alpha", True, {}, env=ENV, runner=interrupted) == 1
    assert "İşlem kesildi." in capsys.readouterr().out


@pytest.mark.parametrize(("key", "repo", "ref"), [
    ("inventory", "home-inventory", "9c431bfe9f7a135a0f75f45cf6909c265c6decc0"),
    ("budget", "budget-stream", "e0a264904bee642e17c66c96526bd032b1f722bc"),
])
def test_bundled_add_preview(key, repo, ref, monkeypatch, capsys):
    monkeypatch.setattr(installer.Environment, "current", lambda: ENV)
    monkeypatch.setattr(metadata, "entry_points", lambda **kw: [])
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: "H")
    assert main(["add", key]) == 0
    output = capsys.readouterr().out
    assert f"-m pip install git+https://github.com/bbnet90/{repo}@{ref}" in output
    assert "İşlem iptal edildi." in output
