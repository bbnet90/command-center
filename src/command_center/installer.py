from dataclasses import dataclass
from difflib import get_close_matches
from pathlib import Path
import os
import shlex
import shutil
import subprocess
import sys
import sysconfig
import tempfile

from .catalog import ID, PROJECT, REF, Module, valid_source
from .catalog_store import load_catalog
from .distributions import normalized
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

    @property
    def uses_pipx(self) -> bool:
        root = self.prefix.parent.parent
        return (self.pipx and self.prefix != self.base_prefix
                and self.prefix.parent.name == "venvs"
                and (root == self.pipx_home or root.name == "pipx"))

    @property
    def target_python(self) -> str:
        if not self.uses_pipx or self.prefix.name == "command-center":
            return self.executable
        # pipx inject explicitly targets the command-center venv.
        relative = "Scripts/python.exe" if os.name == "nt" else "bin/python"
        return str(self.prefix.parent / "command-center" / relative)

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
    pipx = env.uses_pipx
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


def report_orphan(source, env, runner, workdir):
    line("Paket kuruldu ama panel kaydı bulunamadı.")
    try:
        result = runner([env.target_python, "-m", "command_center.distributions", source],
                        cwd=workdir, capture_output=True, text=True)
        dist = result.stdout.removesuffix("\n")
        if result.returncode == 0 and PROJECT.fullmatch(dist):
            line("Kaldırmak için:")
            line(shlex.join(plan(env, dist=dist).argv), plain=True)
            return
    except (OSError, ValueError):
        pass
    line("Kurulan paketin adı belirlenemedi.")


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
            line(item.title, plain=True)
            line(item.source, plain=True)
            line(item.ref or "sürüme sabitlenmemiş", plain=True)
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
                              if normalized(distribution_name(ep) or "") == normalized(dist))
            line(f"Kaldırılacak paket: {dist}")
            line("Etkilenen paneller: " + ", ".join(affected))
            if len(affected) > 1:
                line("Dikkat: Bu paketin tüm panelleri kaldırılacak.")
        if operation.blocked:
            line("Sistem Python ortamı dışarıdan yönetiliyor. Önce command-center aracını pipx ile veya bir sanal ortama kurun.")
            line("pipx ile kurduktan sonra:")
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
            check = runner([env.target_python, "-m", "command_center", "list", "--plain"],
                           cwd=workdir, capture_output=True, text=True)
            if adding and not check.returncode and key not in check.stdout.splitlines():
                report_orphan(item.source, env, runner, workdir)
                return 1
        if check.returncode:
            line("Panel kayıtları doğrulanamadı.")
            return 1
        installed = set(check.stdout.splitlines())
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
