import json

from .paths import state_dir
from .storage import atomic_write


def _stored() -> set[str] | None:
    try:
        document = json.loads((state_dir() / "state.json").read_bytes())
        ids = document["seen"]
        if isinstance(ids, list) and all(isinstance(item, str) for item in ids):
            return set(ids)
    except (OSError, ValueError, KeyError, TypeError, RecursionError):
        pass
    return None


def read_seen(current) -> set[str]:
    seen = _stored()
    if seen is None:
        seen = set(current)
        mark_seen(seen)
    return seen


def mark_seen(ids) -> None:
    data = json.dumps({"seen": sorted((_stored() or set()).union(ids))}).encode()
    try:
        atomic_write(state_dir() / "state.json", data)
    except OSError:
        pass
