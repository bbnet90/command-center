from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tarfile

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
@pytest.mark.parametrize("failure", ["digest", "dependency", "npm", "descriptor", "interrupted", None])
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

    if failure:
        with pytest.raises(KeyboardInterrupt if failure == "interrupted" else ValueError):
            managed.install(item, run)
        assert not managed.record("probe").exists()
        assert not list(managed.prefixes("probe").glob("*"))
        return
    managed.install(item, run)
    entry = configured()[0]["probe"]
    assert Path(entry.argv[0]).is_absolute() and Path(entry.argv[0]).is_file()
    with pytest.raises(ValueError, match="zaten"):
        managed.install(item, run)
    managed.remove("probe", entry.argv[0])
    assert "probe" not in configured()[0]
