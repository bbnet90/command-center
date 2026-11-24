import unicodedata


def clean(text: str) -> str:
    return "".join(c for c in text if unicodedata.category(c) not in {"Cc", "Cf", "Zl", "Zp"})
