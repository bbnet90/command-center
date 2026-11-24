import io
from importlib import resources
import os
from pathlib import Path
from urllib import request
from urllib.error import URLError

import pytest

from command_center import catalog_store as store, state
from command_center.catalog import MAX_BYTES, parse
from command_center.paths import cache_dir, config_dir, state_dir

HEADER = b"format = 1\n"
ROW = b'''[[module]]
id = "alpha"
title = "Alpha"
description = "Local data."
kind = "panel"
source = "Alpha.Project"
'''
DATA = HEADER + ROW


def save(path, data):
    path.parent.mkdir(exist_ok=True, parents=True)
    path.write_bytes(data)


def test_parser():
    data = DATA + b'unknown = "ok"\nref = "1.2"\n' + ROW
    modules, dropped = parse(data)
    assert dropped == 1 and modules["alpha"].ref == "1.2"
    assert not modules["alpha"].featured
    modules, _ = parse(DATA.replace(b"Alpha\"", br"A\u001bl\u0080pha" + b'"'))
    assert modules["alpha"].title == "Alpha"


@pytest.mark.parametrize(("original", "invalid"), [
    ('id = "alpha"', 'id = 2'), ('id = "alpha"', 'id = "-x"'),
    ('title = "Alpha"', 'title = 1'), ('title = "Alpha"', 'title = ""'),
    ('description = "Local data."', 'description = []'),
    ('description = "Local data."', 'description = "' + "x"*201 + '"'),
    ('kind = "panel"', "kind = {}"), ('kind = "panel"', 'kind = "other"'),
    ('source = "Alpha.Project"', 'source = 12'),
    ('source = "Alpha.Project"', 'source = "name"\nfeatured = 1'),
    ('source = "Alpha.Project"', 'source = "name"\nref = 1'),
    ('source = "Alpha.Project"', 'source = "name"\nref = "-branch"'),
])
def test_invalid_entries(original, invalid):
    modules, dropped = parse(HEADER + ROW.replace(original.encode(), invalid.encode()) + ROW)
    assert dropped == 1 and set(modules) == {"alpha"}
    assert modules["alpha"].title == "Alpha"


@pytest.mark.parametrize("source", ["http://host/a", "file:///a", "-e", "git+http://host/a",
                                    "git+https://x@y/z", "git+https://host/a b",
                                    "git+https://host/a?q", "git+https://host/a#frag"])
def test_forbidden_sources(source):
    assert parse(DATA.replace(b"Alpha.Project", source.encode())) == ({}, 1)


@pytest.mark.parametrize("data", [b"format = true", b"format = 2", b"bad", b"x"*(MAX_BYTES+1),
                                  HEADER + ROW*501])
def test_invalid_file(data):
    with pytest.raises(ValueError):
        parse(data)


def test_layers():
    snapshot = resources.files("command_center").joinpath("data", "catalog.toml")
    bundled, dropped = parse(snapshot.read_bytes(), "bundled")
    assert dropped == 0 and bundled and store.load_catalog().modules == bundled
    cache = cache_dir() / "catalog.toml"
    save(cache, DATA)
    os.utime(cache, (10, 10))
    result = store.load_catalog(clock=lambda: 10 + 2*86400)
    assert result.age_days == 2 and result.modules["alpha"].origin == "remote"
    local = config_dir() / "catalog.local.toml"
    save(local, DATA.replace(b'"Alpha"', b'"Override"') + ROW.replace(b'"alpha"', b'"beta"'))
    result = store.load_catalog()
    assert set(result.modules) == {"alpha", "beta"}
    assert result.modules["alpha"].title == "Override"
    assert result.modules["alpha"].origin == "local"
    save(local, b"bad")
    assert store.load_catalog().modules["alpha"].origin == "remote"
    save(cache, b"bad")
    assert store.load_catalog().modules == bundled


@pytest.mark.parametrize(("payload", "url", "status"), [
    (DATA, "https://host/a", store.Status.UPDATED),
    (b"?", "https://host/a", store.Status.INVALID),
    (DATA, "http://host/a", store.Status.INVALID),
    (b"x"*(MAX_BYTES+1), "https://host/a", store.Status.INVALID),
    (URLError("offline"), "", store.Status.OFFLINE),
    (TimeoutError(), "", store.Status.OFFLINE),
])
def test_refresh(monkeypatch, payload, url, status):
    cache = cache_dir() / "catalog.toml"
    save(cache, HEADER)

    class Response(io.BytesIO):
        def geturl(self):
            return url

        def read(self, size):
            assert size == MAX_BYTES + 1
            return super().read(size)

    def fetch(address, *, timeout):
        assert address == store.CATALOG_URL and timeout == 5
        if isinstance(payload, Exception):
            raise payload
        return Response(payload)

    monkeypatch.setattr(request, "urlopen", fetch)
    assert store.refresh(request.urlopen) == status
    assert cache.read_bytes() == (DATA if status == store.Status.UPDATED else HEADER)


def test_disabled(monkeypatch):
    save(config_dir() / "config.toml", b"catalog_refresh=false")
    monkeypatch.setattr(request, "urlopen", lambda *a, **kw: pytest.fail("network"))
    monkeypatch.setattr(request, "build_opener", lambda *a: pytest.fail("network"))
    assert store.refresh() == store.Status.DISABLED


def test_seen():
    assert state.read_seen(["a"]) == {"a"}
    assert state.read_seen(["a", "b"]) == {"a"}
    state.mark_seen({"a", "b"})
    assert state.read_seen([]) == {"a", "b"}
    save(state_dir() / "state.json", b"!")
    assert state.read_seen(["b"]) == {"b"}


def test_generic_core():
    for path in (Path(__file__).parents[1] / "src/command_center").glob("*.py"):
        for forbidden in ("home_inventory", "home-inventory", "budget", "wallet", "todo"):
            assert forbidden not in path.read_text().lower(), path


def test_production_transport(monkeypatch):
    calls = []

    def open_request(self, address, *, timeout):
        calls.append(address)
        handlers = [h for h in self.handlers if isinstance(h, request.HTTPRedirectHandler)]
        assert len(handlers) == 1
        assert handlers[0].redirect_request(None, None, 302, "", {}, "http://host") is None
        raise URLError("offline")

    monkeypatch.setattr(request.OpenerDirector, "open", open_request)
    assert store.refresh() == store.Status.OFFLINE
    assert calls == [store.CATALOG_URL]


def test_mark_adds_ids():
    state.mark_seen(["alpha"])
    state.mark_seen(["beta"])
    assert state.read_seen([]) == {"alpha", "beta"}
