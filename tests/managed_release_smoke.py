"""Exercise the installed dashboard against a real release in a temporary home."""
import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory


def cli(*args):
    output = subprocess.check_output(["command-center", *args], text=True, encoding="utf8")
    print(output)
    return output


def smoke(root):
    for name in ("CONFIG", "DATA", "STATE", "CACHE"):
        os.environ[f"XDG_{name}_HOME"] = str(root / name)
    os.environ.update(HOME=str(root), USERPROFILE=str(root), PYTHONUTF8="1")
    assert shutil.which("todo") is None
    cli("add", "todo", "--yes")
    assert "OK" in cli("check", "todo", "--isolated")
    assert "Görev yok." in cli("--plain")
    from command_center.command_panels import configured
    entry = configured()[0]["todo"]
    assert entry.opening == [entry.argv[0]]
    subprocess.run([*entry.opening, "add", "Persistence check"], env=entry.env, check=True)
    assert "Persistence check" in cli("--plain")
    cli("remove", "todo", "--yes")
    assert not Path(entry.argv[0]).exists()
    cli("add", "todo", "--yes")
    assert "Persistence check" in cli("--plain")


if __name__ == "__main__":
    with TemporaryDirectory() as work:
        smoke(Path(work))
