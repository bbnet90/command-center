import re

CONTROLS = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def clean(text: str) -> str:
    return CONTROLS.sub("", text)
