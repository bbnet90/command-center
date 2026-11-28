from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
from threading import Event, Thread

import pytest

from command_center import managed
from command_center.catalog_store import load_catalog
from command_center.cli import main
from command_center.command_panels import configured
from command_center.paths import config_dir


def archive(manifest, descriptor):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as tar:
        for name, text in [("package.json", json.dumps(manifest)),
                           ("cli.js", "#!/usr/bin/env node\nconsole.log(" + json.dumps(json.dumps(descriptor)) + ")")]:
            data = text.encode()
            info = tarfile.TarInfo("package/" + name)
            info.mode = 0o755
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return stream.getvalue()


@pytest.fixture
def module(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    return load_catalog().modules["todo"]


def test_decline_and_manual_collision(module, monkeypatch):
    from command_center.installer import manage
    monkeypatch.setattr(managed, "download", lambda *_: pytest.fail("unexpected download"))
    assert manage("add", module.id, False, {}, confirm=lambda: False) == 0
    config_dir().mkdir(parents=True)
    config = config_dir() / "config.toml"
    text = '[[command_panel]]\nid="todo"\npanel=["custom"]'
    config.write_text(text)
    assert main(["add", "todo", "--yes"]) == 0
    assert config.read_text() == text and not managed.record("todo").exists()


def test_missing_runtime(module, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda *_: None)
    with pytest.raises(ValueError, match="Node.js"):
        managed.install(module, subprocess.run)


@pytest.mark.skipif(not shutil.which("npm"), reason="npm runtime")
@pytest.mark.parametrize("failure", ["digest", "dependency", "npm", "descriptor", "interrupted", "other-prefix", None])
def test_transaction(module, monkeypatch, failure):
    manifest = {"name": "example-module", "version": "1.2.0", "bin": {"probe": "./cli.js"}}
    descriptor = dict(format=1, id="probe", version="1.2.0", kind="command", title="Probe",
                      panel=["probe", "summary"], open=["probe"])
    if failure == "dependency":
        manifest["dependencies"] = {"example": "1"}
    if failure == "descriptor":
        descriptor["open"] = ["other"]
    data = archive(manifest, descriptor)
    monkeypatch.setattr(managed, "download", lambda _: data)
    item = replace(module, id="probe", executable="probe", sha256=hashlib.sha256(data).hexdigest())
    if failure == "digest":
        item = replace(item, sha256="0" * 64)

    def run(argv, **kwargs):
        assert "--ignore-scripts" in argv and "--offline" in argv
        if failure == "interrupted":
            raise KeyboardInterrupt
        if failure == "npm":
            return subprocess.CompletedProcess(argv, 1)
        return subprocess.run(argv, **kwargs)

    if failure and failure != "other-prefix":
        with pytest.raises(KeyboardInterrupt if failure == "interrupted" else ValueError):
            managed.install(item, run)
        assert not managed.record("probe").exists()
        assert not managed.prefixes("probe").exists()
        return
    managed.install(item, run)
    entry = configured()[0]["probe"]
    assert Path(entry.argv[0]).is_absolute() and Path(entry.argv[0]).is_file()
    with pytest.raises(ValueError, match="zaten"):
        managed.install(item, run)
    leftover = managed.prefixes("probe") / "other-installation"
    if failure == "other-prefix":
        leftover.mkdir()
    old_lock = managed.record("probe").with_suffix(".lock")
    old_lock.touch()
    managed.remove("probe", entry.argv[0])
    assert not old_lock.exists()
    if failure == "other-prefix":
        assert list(leftover.parent.iterdir()) == [leftover]
    else:
        assert not leftover.parent.exists()
    assert "probe" not in configured()[0]


def test_parallel_adds_share_one_lock(module, tmp_path, monkeypatch, capsys):
    from command_center.catalog_store import Catalog
    from command_center.installer import manage

    npm = tmp_path / "npm"
    npm_cli = npm.parent / "node_modules/npm/bin/npm-cli.js"
    npm_cli.parent.mkdir(parents=True)
    npm_cli.touch()
    monkeypatch.setattr(shutil, "which", lambda name: str(npm) if name == "npm" else "node")
    monkeypatch.setattr(subprocess, "check_output", lambda *a, **kw: "v22.0.0")
    started, release = Event(), Event()
    results = []

    def download(source):
        started.set()
        assert release.wait(10)
        return b"bad digest"

    monkeypatch.setattr(managed, "download", download)
    other = replace(module, id="other")
    catalog = Catalog({module.id: module, other.id: other}, None)
    thread = Thread(target=lambda: results.append(manage("add", module.id, True, {}, catalog=catalog)))
    thread.start()
    try:
        assert started.wait(5)
        assert manage("add", other.id, True, {}, catalog=catalog) == 1
        assert "Başka bir modül işlemi sürüyor." in capsys.readouterr().out
    finally:
        release.set()
        thread.join(10)
    assert results == [1]
    assert list(managed.data_dir().iterdir()) == [managed.data_dir() / "modules.lock"]
    assert not list(managed.record(module.id).parent.glob("*.lock"))


@pytest.mark.parametrize(("field", "value", "reason"), [
    ("source", "http://github.com/owner/repo/releases/download/v1/file.tgz", "kaynak HTTPS GitHub release adresi olmalı"),
    ("source", "https://example.test/owner/repo/releases/download/v1/file.tgz", "kaynak HTTPS GitHub release adresi olmalı"),
    ("sha256", "abcd", "sha256 64 küçük onaltılık karakter olmalı"),
    ("executable", "../bad", "executable geçerli komut adı olmalı"),
])
def test_invalid_catalog_entry(module, monkeypatch, capsys, field, value, reason):
    row = dict(id="invalid", title="Example", description="Example", kind="command",
               installer="npm-tarball", source=module.source, sha256=module.sha256,
               executable="probe")
    row[field] = value
    config_dir().mkdir(parents=True)
    text = "format = 1\n[[module]]\n" + "".join(f"{k} = {json.dumps(v)}\n" for k, v in row.items())
    (config_dir() / "catalog.local.toml").write_text(text, encoding="utf8")
    monkeypatch.setattr(managed, "install", lambda *a: pytest.fail("unexpected install"))
    assert "invalid" not in load_catalog().modules
    assert main(["add", "invalid", "--yes"]) == 1
    output = capsys.readouterr().out
    assert "Katalog girişi geçersiz: invalid" in output and reason in output


def test_windows_missing_npm_script(module, tmp_path, monkeypatch):
    npm = tmp_path / "npm.cmd"
    monkeypatch.setattr(shutil, "which", lambda name: str(npm) if name == "npm" else "node.exe")
    with monkeypatch.context() as patch:
        patch.setattr(managed.os, "name", "nt")
        patch.setattr(managed, "Path", type(tmp_path))
        patch.setattr(subprocess, "check_output", lambda *a, **kw: pytest.fail("unexpected process"))
        patch.setattr(managed, "download", lambda *a: pytest.fail("unexpected download"))
        with pytest.raises(ValueError, match="npm-cli.js bulunamadı:") as caught:
            managed.install(module, lambda *a, **kw: pytest.fail("unexpected install"))
    expected = npm.parent / "node_modules/npm/bin/npm-cli.js"
    assert str(caught.value) == f"npm-cli.js bulunamadı: {expected}. Standart bir Node.js kurulumu gerekir."
