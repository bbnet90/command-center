from dataclasses import dataclass
from difflib import get_close_matches
from pathlib import Path
import os
import re
import shlex
import shutil
import subprocess
import sys
import sysconfig
import tempfile

from .catalog import ID, PROJECT, REF, Module, valid_source
from .catalog_store import load_catalog
from .plugins import distribution_name
from .rendering import line


@dataclass(frozen=True)
class Environment:
    prefix: Path
    base_prefix: Path
    executable: str
    pipx: bool
    managed: bool

    pipx_home: Path | None = None

    @classmethod
    def current(cls):
        marker = Path(sysconfig.get_path("stdlib")) / "EXTERNALLY-MANAGED"
        home = os.environ.get("PIPX_HOME")
        return cls(Path(sys.prefix), Path(sys.base_prefix), sys.executable,
                   bool(shutil.which("pipx")), marker.is_file(), Path(home) if home else None)


@dataclass
class Plan:
    argv: list[str]
    blocked: bool = False


def build_spec(module: Module) -> str:
    source, ref = module.source, module.ref
    if not valid_source(source) or (ref is not None and not REF.fullmatch(ref)):
        raise ValueError("Invalid package spec")
    if ref is None:
        return source
    if source.startswith("git+"):
        return f"{source}@{ref}"
    if "/" in ref:
        raise ValueError("Invalid exact version")
    return f"{source}=={ref}"


def plan(env: Environment, *, module: Module | None = None, dist: str | None = None) -> Plan:
    if (module is None) == (dist is None):
        raise ValueError("Expected one package")
    if dist is not None and not PROJECT.fullmatch(dist):
        raise ValueError("Invalid distribution name")
    if not Path(env.executable).is_absolute():
        raise ValueError("Expected an absolute interpreter path")
    venv = env.prefix != env.base_prefix
    root = env.prefix.parent.parent
    pipx_root = root == env.pipx_home or root.name == "pipx"
    pipx = env.pipx and venv and pipx_root and env.prefix.parent.name == "venvs"
    if module is not None:
        spec = build_spec(module)
        if pipx or (not venv and env.managed):
            return Plan(["pipx", "inject", "command-center", spec], not pipx)
        args = ["install"] if venv else ["install", "--user"]
        args.append(spec)
    else:
        args = ["uninstall", "-y", dist]
        if pipx or (not venv and env.managed):
            return Plan(["pipx", "runpip", "command-center", *args], not pipx)
    return Plan([env.executable, "-m", "pip", *args])


def _normalized(name: str) -> str:
    return re.sub("[-_.]+", "-", name).lower()


def manage(action, key, yes, entries, *, env=None, runner=None) -> int:
    if action not in ("add", "remove"):
        raise ValueError("Unknown package operation")
    if runner is None:
        runner = subprocess.run
    env = env or Environment.current()
    adding = action == "add"
    if not ID.fullmatch(key) and (adding or key not in entries):
        line("Geçersiz modül kimliği.")
        return 2
    try:
        if adding:
            if key in entries:
                line("Bu modül zaten kurulu.")
                return 0
            modules = load_catalog().modules
            item = modules.get(key)
            if item is None:
                line(f"Bilinmeyen modül: {key}")
                matches = get_close_matches(key, modules)
                if matches:
                    line("Benzer kimlikler: " + ", ".join(matches))
                return 1
            if item.kind != "panel":
                line("Bu tür henüz desteklenmiyor")
                return 1
            operation = plan(env, module=item)
            line(f"{item.title} · {item.source} · {item.ref or 'sürüme sabitlenmemiş'}")
        else:
            if key not in entries:
                line("Bu panel kurulu değil.")
                return 1
            dist = distribution_name(entries[key])
            if not dist:
                line("Panelin paket adı belirlenemedi.")
                return 1
            operation = plan(env, dist=dist)
            affected = sorted(k for k, ep in entries.items()
                              if _normalized(distribution_name(ep) or "") == _normalized(dist))
            line(f"Kaldırılacak paket: {dist}")
            line("Etkilenen paneller: " + ", ".join(affected))
            if len(affected) > 1:
                line("Dikkat: Bu paketin tüm panelleri kaldırılacak.")
        if operation.blocked:
            line("Sistem Python ortamı dışarıdan yönetiliyor. pipx veya sanal ortam kullanın.")
        line(shlex.join(operation.argv), plain=True)
        if adding:
            line("Bu işlem üçüncü taraf kod kurar.")
        if operation.blocked:
            return 1
        if not yes:
            if not sys.stdin.isatty():
                line("Etkileşimsiz kullanım için --yes gerekli.")
                return 1
            if input("Devam edilsin mi? [e/H] ").strip().casefold() != "e":
                line("İşlem iptal edildi.")
                return 0
        # An unrelated local directory must never shadow a registry project name.
        with tempfile.TemporaryDirectory() as workdir:
            if runner(operation.argv, cwd=workdir).returncode:
                line("Paket işlemi başarısız.")
                return 1
            check = runner([env.executable, "-m", "command_center", "list", "--plain"],
                           cwd=workdir, capture_output=True, text=True)
        if check.returncode:
            line("Panel kayıtları doğrulanamadı.")
            return 1
        installed = set(check.stdout.splitlines())
        if adding and key not in installed:
            line("Kuruldu ama panel kaydı bulunamadı")
            line("Modül henüz command_center.panels giriş noktasını sunmuyor olabilir.")
            return 1
        if not adding and installed.intersection(affected):
            line("Kaldırma doğrulanamadı.")
            return 1
        line("Kuruldu ve bağlandı." if adding else "Paket kaldırıldı.")
        return 0
    except (EOFError, KeyboardInterrupt):
        line("İşlem kesildi.")
    except (OSError, ValueError):
        line("Paket işlemi gerçekleştirilemedi.")
    return 1
