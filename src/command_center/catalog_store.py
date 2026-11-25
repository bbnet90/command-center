from dataclasses import dataclass
from enum import Enum, auto
from http.client import HTTPException
from importlib import resources
import os
import time
from urllib import request
from urllib.error import HTTPError
from urllib.parse import urlsplit

from .catalog import MAX_BYTES, Module, parse
from .config import refresh_enabled
from .paths import cache_dir, config_dir
from .storage import atomic_write

CATALOG_URL = "https://raw.githubusercontent.com/bbnet90/command-center-catalog/main/catalog.toml"


class Status(Enum):
    UPDATED = auto()
    OFFLINE = auto()
    UNAVAILABLE = auto()
    INVALID = auto()
    DISABLED = auto()


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass(frozen=True)
class RefreshResult:
    status: Status
    http_code: int | None = None


def refresh(open_url=None) -> Status:
    return refresh_result(open_url).status


def refresh_result(open_url=None) -> RefreshResult:
    if not refresh_enabled():
        return RefreshResult(Status.DISABLED)
    if open_url is None:
        open_url = request.build_opener(NoRedirect()).open
    try:
        with open_url(CATALOG_URL, timeout=5) as response:
            if urlsplit(response.geturl()).scheme != "https":
                return RefreshResult(Status.INVALID)
            data = response.read(MAX_BYTES + 1)
        modules, _ = parse(data)
        if not modules:
            return RefreshResult(Status.INVALID)
        atomic_write(cache_dir() / "catalog.toml", data)
    except HTTPError as exc:
        exc.close()
        if 400 <= exc.code < 600:
            return RefreshResult(Status.UNAVAILABLE, exc.code)
        return RefreshResult(Status.INVALID)
    except (OSError, HTTPException):
        return RefreshResult(Status.OFFLINE)
    except (ValueError, RecursionError):
        return RefreshResult(Status.INVALID)
    return RefreshResult(Status.UPDATED)


@dataclass
class Catalog:
    modules: dict[str, Module]
    age_days: int | None


def load_catalog(clock=time.time) -> Catalog:
    age = None
    try:
        with (cache_dir() / "catalog.toml").open("rb") as stream:
            modules, _ = parse(stream.read(MAX_BYTES + 1), "remote")
            age = max(0, int((clock() - os.fstat(stream.fileno()).st_mtime) // 86400))
    except (OSError, ValueError, RecursionError):
        snapshot = resources.files("command_center").joinpath("data", "catalog.toml")
        modules, _ = parse(snapshot.read_bytes(), "bundled")
    try:
        with (config_dir() / "catalog.local.toml").open("rb") as stream:
            overrides, _ = parse(stream.read(MAX_BYTES + 1), "local")
        modules.update(overrides)
    except (OSError, ValueError, RecursionError):
        pass
    return Catalog(modules, age)


def footer(catalog, status=None, http_code=None):
    if status == Status.UPDATED:
        yield "Kaynak: güncel indirme"
    elif catalog.age_days is None:
        yield "Kaynak: çatıyla gelen liste"
    else:
        yield f"Kaynak: önbellek ({catalog.age_days} gün önce)"
    if status == Status.INVALID:
        yield "Katalog dosyası geçersiz"
    if status == Status.OFFLINE:
        yield "Çevrimdışı: yenilenemedi"
    if status == Status.UNAVAILABLE:
        yield f"Katalog alınamadı (HTTP {http_code})"
