from typing import TypedDict

from .text import clean


MAX_LINES = 100
MAX_CHARS = 300


class PanelData(TypedDict):
    title: str
    lines: list[str]


def validate(value: object) -> PanelData:
    if not isinstance(value, dict):
        raise ValueError("Panel bir sözlük olmalı.")
    title = value.get("title")
    lines = value.get("lines")
    if not isinstance(title, str) or not clean(title).strip():
        raise ValueError("title boş olmayan bir metin olmalı.")
    if not isinstance(lines, list) or not all(isinstance(line, str) for line in lines):
        raise ValueError("lines yalnızca metin içeren bir liste olmalı.")
    output = []
    truncated = len(lines) > MAX_LINES
    for raw in lines[:MAX_LINES]:
        text = clean(raw)
        truncated |= len(text) > MAX_CHARS
        output.append(text[:MAX_CHARS])
    if truncated:
        output[MAX_LINES - 1:] = ["… (kısaltıldı)"]
    return {"title": clean(title), "lines": output}
