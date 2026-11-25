"""Read explicitly configured command panels and bound their subprocesses."""
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from threading import Lock, Thread, Timer

from .catalog import ID
from .config import settings
from .contract import valid_argv

MAX_OUTPUT = 65536


def kill_group(proc):
    try:
        if os.name == "posix":
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            proc.kill()
    except ProcessLookupError:
        pass


class Processes:
    def __init__(self):
        self.lock = Lock()
        self.active = set()
        self.closed = False

    def start(self, argv, **kwargs):
        with self.lock:
            if self.closed:
                raise RuntimeError("Uygulama kapanıyor.")
            proc = subprocess.Popen(argv, start_new_session=os.name == "posix", **kwargs)
            self.active.add(proc)
            return proc

    def finish(self, proc):
        with self.lock:
            kill_group(proc)
            proc.wait()
            self.active.discard(proc)

    def close(self):
        with self.lock:
            self.closed = True
            for proc in self.active:
                kill_group(proc)


@dataclass
class CommandPanel:
    name: str
    argv: list[str]
    title: str
    opening: list[str] | None
    timeout: int
    processes: Processes = field(repr=False)
    env: dict | None = None

    def load(self):
        return self.read

    def read(self):
        home = self.env["HOME"] if self.env is not None else Path.home()
        proc = self.processes.start(self.argv, cwd=home, env=self.env, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        diagnostics = bytearray()

        def drain_errors():
            with proc.stderr:
                while chunk := proc.stderr.read(8192):
                    diagnostics.extend(chunk[:MAX_OUTPUT - len(diagnostics)])

        reader = Thread(target=drain_errors, daemon=True)
        reader.start()
        expired = False

        def timeout():
            nonlocal expired
            expired = True
            kill_group(proc)

        timer = Timer(self.timeout, timeout)
        timer.daemon = True
        timer.start()
        try:
            with proc.stdout:
                raw = proc.stdout.read(MAX_OUTPUT + 1)
            if len(raw) > MAX_OUTPUT:
                raise ValueError("Çıktı 64 KiB sınırını aştı.")
            code = proc.wait()
            if expired:
                raise TimeoutError("Komut zaman aşımına uğradı.")
            if code:
                raise ValueError(f"Komut çıkış kodu: {code}")
        finally:
            timer.cancel()
            timer.join()
            self.processes.finish(proc)
            reader.join()
            sys.stderr.write(diagnostics.decode("utf-8", errors="replace"))
        result = json.loads(raw.decode("utf-8"))
        if isinstance(result, dict):
            result.setdefault("title", self.title)
            if self.opening:
                result["open"] = self.opening
        return result


def configured(processes=None):
    entries, errors = {}, []
    rows = settings().get("command_panel", [])
    if not isinstance(rows, list):
        return {}, ["command_panel liste olmalı."]
    processes = processes or Processes()
    for index, row in enumerate(rows, 1):
        if isinstance(row, dict):
            key = row.get("id")
            title = row.get("title", key)
            seconds = row.get("timeout", 10)
            if (isinstance(key, str) and ID.fullmatch(key) and key not in entries
                    and isinstance(title, str) and title.strip()
                    and valid_argv(row.get("panel"))
                    and ("open" not in row or valid_argv(row["open"]))
                    and type(seconds) is int and 1 <= seconds <= 30):
                entries[key] = CommandPanel(key, row["panel"], title, row.get("open"), seconds, processes)
                continue
        errors.append(f"command_panel[{index}] geçersiz veya yinelenmiş.")
    return entries, errors
