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
    os.environ.update(HOME=str(root), USERPROFILE=str(root), APPDATA=str(root / "roaming"), PYTHONUTF8="1")
    os.environ.pop("TODO_CLI_DATA_FILE", None)
    assert shutil.which("todo") is None
    cli("add", "todo", "--yes")
    assert "OK" in cli("check", "todo", "--isolated")
    assert "Görev yok." in cli("--plain")
    from command_center.command_panels import configured
    from command_center.managed import data_dir, prefixes, record
    entry = configured()[0]["todo"]
    assert entry.opening == [entry.argv[0]]
    subprocess.run([*entry.opening, "add", "Persistence check"], env=entry.env, check=True)
    user_data = Path(os.environ["APPDATA" if os.name == "nt" else "XDG_DATA_HOME"])
    tasks = user_data / "todo-cli" / "tasks.json"
    snapshot = tasks.read_bytes()
    assert "Persistence check" in cli("--plain")
    cli("remove", "todo", "--yes")
    assert tasks.read_bytes() == snapshot
    assert not Path(entry.argv[0]).exists()
    module_record = record("todo")
    package_root = prefixes("todo")
    assert list(module_record.parent.iterdir()) == []
    assert list(package_root.parent.iterdir()) == []
    assert (data_dir() / "modules.lock").is_file()
    print("After remove: modules.d=[], packages=[], modules.lock=present")
    cli("add", "todo", "--yes")
    assert list(module_record.parent.iterdir()) == [module_record]
    assert list(package_root.parent.iterdir()) == [package_root]
    assert len(list(package_root.iterdir())) == 1
    print("After reinstall: modules.d=[todo.toml], packages/todo=[one prefix], modules.lock=present")
    assert "Persistence check" in cli("--plain")


if __name__ == "__main__":
    with TemporaryDirectory() as work:
        smoke(Path(work))
