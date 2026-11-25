from dataclasses import replace
from .command_panels import CommandPanel
from difflib import get_close_matches
import os
from pathlib import Path
import site
import subprocess
import sys
import tempfile

from rich.cells import cell_len

from .plugins import conflicts, package_label, inspect_panel
from .rendering import PANEL_WIDTH, line


def _report(entry) -> bool:
    result = inspect_panel(entry)
    lines = result.panel["lines"] if result.panel else []
    width = max(map(cell_len, lines), default=0)
    status = "FAIL" if result.error else "OK"
    line(f"{entry.name} · {package_label(entry)} · {status} · "
         f"{result.elapsed_ms:.2f} ms · {len(lines)} satır · en geniş: {width}")
    if result.invalid_open:
        line("Uyarı: open komutu geçersiz.")
    if result.error:
        line(result.error)
    if width > PANEL_WIDTH - 4:
        line(f"Uyarı: Satır genişliği {PANEL_WIDTH - 4} sütunu aşıyor.")
    for label, output in (("stdout", result.stdout), ("stderr", result.stderr)):
        if output:
            line(f"Uyarı: {label}")
            for row in output.splitlines():
                line(row)
    return result.error is None


def _isolated(key, runner, entry=None) -> bool:
    with tempfile.TemporaryDirectory() as workdir:
        root = Path(workdir)
        env = os.environ.copy()
        # Preserve access to modules installed with pip --user after changing HOME.
        if site.ENABLE_USER_SITE:
            env.setdefault("PYTHONUSERBASE", site.getuserbase())
        if "PYTHONPATH" in env:
            env["PYTHONPATH"] = os.pathsep.join(
                os.path.abspath(p) for p in env["PYTHONPATH"].split(os.pathsep)
            )
        for name in ("HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME", "XDG_DATA_HOME"):
            env[name] = workdir
        args = [sys.executable, "-m", "command_center", "check"]
        if key.startswith("-"):
            args.append("--")
        if isinstance(entry, CommandPanel):
            code = int(not _report(replace(entry, env=env)))
        else:
            code = runner([*args, key], env=env, cwd=workdir).returncode
        created = sorted(str(path.relative_to(root)) for path in root.rglob("*"))
        if created:
            line(f"{key} · FAIL · panel dosya oluşturdu: " + ", ".join(created))
        elif code:
            line(f"{key} · FAIL")
        return code == 0 and not created


def check(entries, key=None, *, isolated=False, runner=None) -> int:
    if key is not None and key not in entries:
        line(f"Bilinmeyen panel: {key}")
        matches = get_close_matches(key, entries)
        if matches:
            line("Benzer kimlikler: " + ", ".join(matches))
        return 1
    duplicates = conflicts()
    ok = True
    for name in ([key] if key is not None else sorted(entries)):
        if name in duplicates:
            line(f"Giriş noktası çakışması: {name} · " + ", ".join(duplicates[name]))
        if isolated:
            try:
                passed = _isolated(name, runner or subprocess.run, entries[name])
            except (OSError, ValueError) as exc:
                line(f"{name} · FAIL · {exc}")
                passed = False
        else:
            passed = _report(entries[name])
        ok = ok and passed
    return 0 if ok else 1
