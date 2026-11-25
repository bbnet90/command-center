"""Own the dashboard's package manager and its verification processes."""
import asyncio
import os
import signal
import subprocess
from threading import Lock


class PackageProcess:
    def __init__(self):
        self.lock = Lock()
        self.child = None
        self.closing = False

    def run(self, argv, *, emit, cwd, capture_output=False, text=True):
        with self.lock:
            if self.closing:
                raise OSError("Application closing")
            proc = subprocess.Popen(
                argv, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE if capture_output else subprocess.STDOUT,
                text=True, errors="replace", start_new_session=os.name == "posix",
            )
            self.child = proc
        try:
            with proc:
                if capture_output:
                    out, err = proc.communicate()
                else:
                    for row in proc.stdout:
                        emit(row.rstrip("\n"))
                    out = err = None
                return subprocess.CompletedProcess(argv, proc.wait(), out, err)
        finally:
            with self.lock:
                self.child = None

    async def shutdown(self):
        with self.lock:
            self.closing = True
            proc = self.child
        if proc is None:
            return
        if os.name == "posix":
            try:
                os.killpg(proc.pid, signal.SIGTERM)
                for _ in range(60):
                    await asyncio.sleep(.05)
                    os.killpg(proc.pid, 0)
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        elif proc.poll() is None:
            proc.terminate()
            for _ in range(60):
                if proc.poll() is not None:
                    return
                await asyncio.sleep(.05)
            proc.kill()
