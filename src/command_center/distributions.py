"""Identify an installed distribution from metadata in the active interpreter."""

from importlib import metadata
import json
import re
import sys

from .catalog import PROJECT, valid_source


def normalized(name: str) -> str:
    return re.sub("[-_.]+", "-", name).lower()


def resolve(source: str) -> str | None:
    if not valid_source(source):
        return None
    project = PROJECT.fullmatch(source)
    matches = set()
    for dist in metadata.distributions():
        name = dist.metadata.get("Name")
        if not name or not PROJECT.fullmatch(name):
            continue
        if project:
            if normalized(name) == normalized(source):
                matches.add(normalized(name))
            continue
        try:
            direct = json.loads(dist.read_text("direct_url.json") or "{}")
        except (ValueError, OSError, RecursionError):
            continue
        if isinstance(direct, dict) and direct.get("url") == source.removeprefix("git+"):
            matches.add(normalized(name))
    return matches.pop() if len(matches) == 1 else None


if __name__ == "__main__":
    name = resolve(sys.argv[1])
    if name is None:
        sys.exit(1)
    print(name)
