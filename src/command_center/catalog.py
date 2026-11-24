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


def valid_source(source: str) -> bool:
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
    panel_id, title, description, kind, source = (
        row[key] for key in ("id", "title", "description", "kind", "source")
    )
    ref = row.get("ref")
    featured = row.get("featured", False)
    if not all(isinstance(v, str) for v in (panel_id, title, description, kind, source)):
        raise ValueError
    title, description = clean(title).strip(), clean(description).strip()
    if not (ID.fullmatch(panel_id) and 0 < len(title) <= 60 and 0 < len(description) <= 200):
        raise ValueError
    if kind not in ("panel", "command", "llm") or not valid_source(source):
        raise ValueError
    if ref is not None and not (isinstance(ref, str) and REF.fullmatch(ref)):
        raise ValueError
    if not isinstance(featured, bool):
        raise ValueError
    return Module(panel_id, title, description, kind, source, ref, featured, origin)


def parse(data: bytes, origin: str = "local") -> tuple[dict[str, Module], int]:
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
        except (ValueError, KeyError, TypeError):
            continue
        modules.setdefault(item.id, item)
    return modules, len(rows) - len(modules)
