from importlib import metadata
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError

import pytest

from command_center import catalog_store, installer
from command_center.catalog import Module, parse, valid_source
from command_center.cli import main
from command_center.contract import validate
from command_center.distributions import resolve


@pytest.mark.parametrize("source", [
    "pаckage", "git+https://hоst/repo", "git+https://host/%D0%B0",
    "git+https://host/%FF", "git+https://host/a\u202eb",
])
def test_ascii_sources(source):
    assert not valid_source(source)


def test_clean_display_text():
    letters = "ğüşıöçİĞÜŞÖÇ"
    raw = letters + "\u202e\u200b\u2028\u2029\x1b\x85"
    assert validate({"title": raw, "lines": [raw]}) == {"title": letters, "lines": [letters]}
    data = f'''format = 1
[[module]]
id="a"
title="{raw[:-2]}"
description="{raw[:-2]}"
kind="panel"
source="a"
'''
    items, drops = parse(data.encode())
    assert drops == 0
    assert items["a"].title == items["a"].description == letters


@pytest.mark.parametrize(("code", "status", "footer"), [
    (404, catalog_store.Status.UNAVAILABLE, "Katalog alınamadı (HTTP 404)"),
    (503, catalog_store.Status.UNAVAILABLE, "Katalog alınamadı (HTTP 503)"),
    (302, catalog_store.Status.INVALID, "Katalog dosyası geçersiz"),
])
def test_http_failure(code, status, footer, monkeypatch, capsys):
    def fetch(*args, **kwargs):
        raise HTTPError(catalog_store.CATALOG_URL, code, "error", {}, None)

    result = catalog_store.refresh_result(fetch)
    assert result.status is status
    assert catalog_store.refresh(fetch) is status
    monkeypatch.setattr(catalog_store, "refresh_result", lambda: result)
    monkeypatch.setattr(metadata, "entry_points", lambda **kw: [])
    assert main(["catalog"]) == 0
    assert capsys.readouterr().out.splitlines()[-1] == footer


def test_resolve_from_metadata(monkeypatch):
    url = "https://host/repo"

    def dist(name, metadata_text):
        return SimpleNamespace(metadata={"Name": name}, read_text=lambda _: metadata_text)

    items = [dist("Actual_Name", '{"url":"https://host/repo"}'), dist("unrelated", "broken")]
    monkeypatch.setattr(metadata, "distributions", lambda: iter(items))
    assert resolve("actual.name") == "actual-name"
    assert resolve("missing") is None
    assert resolve("git+" + url) == "actual-name"
    assert resolve("git+" + url + "2") is None
    items.append(dist("Different", '{"url":"https://host/repo"}'))
    assert resolve("git+" + url) is None


@pytest.mark.parametrize("resolved", ["actual-dist\n", "", "--invalid\n"])
def test_orphan_plan(resolved, monkeypatch, capsys):
    item = Module("p", "Başlık", "A panel", "panel", "git+https://host/repo")
    env = installer.Environment(Path("/v"), Path("/sys"), "/v/bin/python", False, False)
    monkeypatch.setattr(installer, "load_catalog", lambda: catalog_store.Catalog({"p": item}, None))
    calls = []

    def runner(argv, *, cwd, **kw):
        assert Path(cwd).is_dir()
        calls.append((argv, cwd))
        return SimpleNamespace(returncode=0, stdout=resolved if len(calls) == 3 else "")

    assert installer.manage("add", "p", True, {}, env=env, runner=runner) == 1
    assert len(calls) == 3 and len({cwd for _, cwd in calls}) == 1
    assert calls[-1][0] == [env.executable, "-m", "command_center.distributions", item.source]
    output = capsys.readouterr().out.splitlines()
    assert output[:3] == [item.title, item.source, "sürüme sabitlenmemiş"]
    assert "Paket kuruldu ama panel kaydı bulunamadı." in output
    if resolved.startswith("actual"):
        assert output[-2:] == ["Kaldırmak için:", "/v/bin/python -m pip uninstall -y actual-dist"]
    else:
        assert "belirlenemedi" in output[-1] and "Kaldırmak için:" not in output


def test_managed_instructions(monkeypatch, capsys):
    env = installer.Environment(Path("/sys"), Path("/sys"), "/sys/bin/python", False, True)
    item = Module("p", "Panel", "Example", "panel", "p", ref="1")
    monkeypatch.setattr(installer, "load_catalog", lambda: catalog_store.Catalog({"p": item}, None))
    assert installer.manage("add", "p", True, {}, env=env, runner=lambda *a: pytest.fail()) == 1
    output = capsys.readouterr().out
    assert "Önce command-center" in output
    assert "pipx ile kurduktan sonra:\npipx inject command-center p==1" in output


def test_pipx_orphan_uses_target_python(monkeypatch, capsys):
    root = Path("/pipx/venvs")
    env = installer.Environment(root / "other", Path("/sys"),
                                str(root / "other/bin/python"), True, False)
    item = Module("p", "Panel", "Example", "panel", "dist-name")
    monkeypatch.setattr(installer, "load_catalog", lambda: catalog_store.Catalog({"p": item}, None))
    calls = []

    def runner(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(returncode=0, stdout="dist-name\n" if len(calls) == 3 else "")

    assert installer.manage("add", "p", True, {}, env=env, runner=runner) == 1
    assert calls[0] == ["pipx", "inject", "command-center", "dist-name"]
    assert all(argv[0] == str(root / "command-center/bin/python") for argv in calls[1:])
    assert capsys.readouterr().out.splitlines()[-1] == "pipx runpip command-center uninstall -y dist-name"
