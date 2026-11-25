from importlib import metadata

FALLBACK = "0.2.0"


def version():
    try:
        return metadata.version("command-center")
    except metadata.PackageNotFoundError:
        return FALLBACK
