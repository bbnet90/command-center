"""Installed CLI smoke test for the Windows Actions runner."""
import asyncio
import os
import select
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import time


def smoke(root, shim):
    from winpty import PtyProcess

    config = root / "command-center"
    config.mkdir()
    (config / "config.toml").write_text(
        '[[command_panel]]\nid="todo"\npanel=["todo","panel","--json"]\nopen=["todo"]\n'
    )
    os.environ.update(XDG_CONFIG_HOME=str(root), TODO_CLI_DATA_FILE=str(root / "tasks.json"))
    if shim:
        (root / "todo.cmd").write_text(
            '@echo off\nif "%1"=="" goto opened\n'
            'echo {"title":"Shim","lines":["shim-ok"],"open":["todo"]}\nexit /b 0\n'
            ':opened\necho SHIM-OPENED\n', encoding="ascii"
        )
        os.environ["PATH"] = str(root) + os.pathsep + os.environ["PATH"]
    target = shutil.which("todo")
    assert target and target.lower().endswith(".cmd"), target
    for args, expected in [
        (["check", "todo", "--isolated"], ["OK", target]),
        (["--plain"], ["shim-ok" if shim else "Görev yok."]),
        (["doctor"], [target]),
    ]:
        output = subprocess.check_output(["command-center", *args], text=True, encoding="utf-8")
        print(output, flush=True)
        assert all(marker in output for marker in expected)

    # Give the real Node CLI a Windows console for its raw keyboard input.
    child = PtyProcess.spawn([sys.executable, __file__, "open"])
    output = ""
    opened = False
    marker = "SHIM-OPENED" if shim else "TODO LIST"
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                if not select.select([child.fileobj], [], [], .2)[0]:
                    continue
                output += child.read(4096)
            except EOFError:
                break
            if marker in output and not opened:
                opened = True
                if not shim:
                    child.write("q")
            if "OPEN-RETURNED" in output:
                break
            time.sleep(.05)
        print(output, flush=True)
        assert marker in output and "OPEN-RETURNED" in output
    finally:
        child.close(force=True)


if __name__ == "__main__":
    if sys.argv[1] == "open":
        from command_center.command_panels import configured
        from command_center.shell import Dashboard

        entries, _ = configured()
        asyncio.run(Dashboard().run_open(entries["todo"].opening))
        print("OPEN-RETURNED")
    else:
        with TemporaryDirectory() as tmp:
            smoke(Path(tmp), sys.argv[1] == "shim")
