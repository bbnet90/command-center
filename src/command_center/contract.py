from typing import TypedDict


class PanelData(TypedDict):
    title: str
    lines: list[str]


def validate(value: object) -> PanelData:
    if not isinstance(value, dict):
        raise ValueError("Expected a panel dictionary")
    title = value.get("title")
    lines = value.get("lines")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("Expected a non-empty title")
    if not isinstance(lines, list) or not all(isinstance(line, str) for line in lines):
        raise ValueError("Expected a list of strings")
    return {"title": title, "lines": lines}
