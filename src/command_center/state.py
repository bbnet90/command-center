import json

from .paths import state_dir
from .storage import atomic_write


def preferences() -> dict:
    try:
        document = json.loads((state_dir() / "state.json").read_bytes())
        return document if isinstance(document, dict) else {}
    except (OSError, ValueError, RecursionError):
        return {}


def _stored() -> set[str] | None:
    ids = preferences().get("seen")
    if isinstance(ids, list) and all(isinstance(item, str) for item in ids):
        return set(ids)
    return None


def read_seen(current) -> set[str]:
    seen = _stored()
    if seen is None:
        seen = set(current)
        mark_seen(seen)
    return seen


def mark_seen(ids) -> None:
    save(seen=sorted((_stored() or set()).union(ids)))


def save(**values) -> None:
    data = json.dumps({**preferences(), **values}).encode()
    try:
        atomic_write(state_dir() / "state.json", data)
    except OSError:
        pass
