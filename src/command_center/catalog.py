from dataclasses import dataclass
import re
import tomllib
from urllib.parse import unquote, urlsplit

from .text import clean

MAX_BYTES = 256 * 1024
ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}")
PROJECT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,63}")


@dataclass(frozen=True)
class Module:
    id: str
    title: str
    description: str
    kind: str
    source: str
    ref: str | None = None
    featured: bool = False
    origin: str = "local"
    installer: str | None = None
    sha256: str | None = None
    executable: str | None = None
    data_file_env: str | None = None


def valid_source(source: str) -> bool:
    if not source.isascii() or not unquote(source).isascii():
        return False
    if PROJECT.fullmatch(source):
        return True
    if not source.startswith("git+https://"):
        return False
    decoded = unquote(source)
    if clean(decoded) != decoded or any(c.isspace() for c in decoded):
        return False
    # An inline @revision or #fragment changes pip's interpretation of a URL.
    if any(c in decoded for c in "?#@\\"):
        return False
    try:
        url = urlsplit(source)
        _ = url.port  # Access validates the port.
        return bool(url.hostname and url.path.strip("/"))
    except ValueError:
        return False


def _entry(row: dict, origin: str) -> Module:
    if not isinstance(row, dict):
        raise ValueError("girdi bir tablo olmalı")
    panel_id, title, description, kind, source = (
        row.get(key) for key in ("id", "title", "description", "kind", "source")
    )
    ref = row.get("ref")
    featured = row.get("featured", False)
    if not all(isinstance(v, str) for v in (panel_id, title, description, kind, source)):
        raise ValueError("id, title, description, kind ve source metin olmalı")
    title, description = clean(title).strip(), clean(description).strip()
    if not (ID.fullmatch(panel_id) and 0 < len(title) <= 60 and 0 < len(description) <= 200):
        raise ValueError("kimlik, başlık veya açıklama geçersiz")
    if kind not in ("panel", "command", "llm"):
        raise ValueError("kind geçersiz")
    installer = row.get("installer")
    digest, executable, variable = (row.get(k) for k in ("sha256", "executable", "data_file_env"))
    if installer is not None:
        if installer != "npm-tarball" or kind != "command" or ref is not None:
            raise ValueError("installer, kind veya ref geçersiz")
        if not re.fullmatch(r"https://github[.]com/[\w.-]+/[\w.-]+/releases/download/[\w.-]+/[\w.-]+[.]tgz",
                            source, re.ASCII):
            raise ValueError("kaynak HTTPS GitHub release adresi olmalı")
        if not isinstance(digest, str) or not re.fullmatch("[0-9a-f]{64}", digest):
            raise ValueError("sha256 64 küçük onaltılık karakter olmalı")
        if not isinstance(executable, str) or not ID.fullmatch(executable):
            raise ValueError("executable geçerli komut adı olmalı")
        if variable is not None and (not isinstance(variable, str)
                                     or not re.fullmatch(r"[A-Z][A-Z0-9_]*_DATA_FILE", variable)):
            raise ValueError("data_file_env geçersiz")
    elif not valid_source(source):
        raise ValueError("kaynak geçersiz")
    if ref is not None and not (isinstance(ref, str) and REF.fullmatch(ref)):
        raise ValueError("ref geçersiz")
    if not isinstance(featured, bool):
        raise ValueError("featured doğru veya yanlış olmalı")
    return Module(panel_id, title, description, kind, source, ref, featured, origin, installer, digest, executable, variable)


def parse(data: bytes, origin: str = "local", *, invalid: dict[str, str] | None = None) -> tuple[dict[str, Module], int]:
    if len(data) > MAX_BYTES:
        raise ValueError("Catalog too large")
    document = tomllib.loads(data.decode("utf-8"))
    if type(document.get("format")) is not int or document["format"] != 1:
        raise ValueError("Unsupported format")
    rows = document.get("module", [])
    if not isinstance(rows, list) or len(rows) > 500:
        raise ValueError("Invalid module list")
    modules = {}
    for row in rows:
        try:
            item = _entry(row, origin)
        except ValueError as exc:
            key = row.get("id") if isinstance(row, dict) else None
            if invalid is not None and isinstance(key, str) and ID.fullmatch(key):
                invalid.setdefault(key, str(exc))
            continue
        modules.setdefault(item.id, item)
    if invalid is not None:
        for key in modules:
            invalid.pop(key, None)
    return modules, len(rows) - len(modules)
