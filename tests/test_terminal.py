import os
from pathlib import Path
import select
import shutil
import signal
import subprocess
import sys
import time

import pytest

pty = pytest.importorskip("pty")
import fcntl
import struct
import termios


@pytest.mark.parametrize("scenario", ["q", "ctrl-c", "term", "hup", "empty", "first-frame"])
def test_terminal_exit(tmp_path, scenario):
    config = tmp_path / "command-center"
    config.mkdir()
    (config / "config.toml").write_text("catalog_refresh=false")
    if scenario != "empty":
        info = tmp_path / "probe-0.1.dist-info"
        info.mkdir()
        (info / "METADATA").write_text("Name: probe\nVersion: 0.1\n")
        (info / "entry_points.txt").write_text("[command_center.panels]\nprobe = probe:panel\n")
        body = ("return {'title':'FirstFrameTitle','lines':['ready']}" if scenario == "first-frame"
                else "Path(__file__).with_suffix('.started').touch(); time.sleep(120)")
        (tmp_path / "probe.py").write_text(
            "from pathlib import Path\nimport time\ndef panel():\n    " + body + "\n"
        )
    env = dict(os.environ, TERM="xterm-256color", HOME=str(tmp_path),
               XDG_CONFIG_HOME=str(tmp_path), PYTHONPATH=str(tmp_path))
    binary = shutil.which("command-center", path=str(Path(sys.executable).parent)) or shutil.which("command-center")
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 100, 0, 0))
    start = time.monotonic()
    child = subprocess.Popen([binary], env=env, stdin=slave, stdout=slave, stderr=slave)
    os.close(slave)
    try:
        output = bytearray()
        expected = {"first-frame": "FirstFrameTitle", "empty": "Başlamak için bir modül seç"}.get(scenario, "probe")
        while time.monotonic() - start < 3:
            if select.select([master], [], [], .05)[0]:
                output.extend(os.read(master, 65536))
            if expected.encode() in output and (scenario in ("empty", "first-frame")
                                                or (tmp_path / "probe.started").exists()):
                break
        else:
            pytest.fail(f"Missing frame or worker start: {output[-1500:]!r}")
        if scenario in ("term", "hup"):
            child.send_signal(signal.SIGTERM if scenario == "term" else signal.SIGHUP)
        else:
            os.write(master, b"\x03" if scenario == "ctrl-c" else b"q")
        deadline = time.monotonic() + 3
        # Keep draining the terminal while Textual restores it.
        while child.poll() is None and time.monotonic() < deadline:
            if select.select([master], [], [], .03)[0]:
                try:
                    os.read(master, 65536)
                except OSError:
                    pass
        assert child.poll() == 0
    finally:
        if child.poll() is None:
            child.kill()
        child.wait()
        os.close(master)
