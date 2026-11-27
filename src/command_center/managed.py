"""Install pinned, dependency-free npm command modules into private prefixes."""
from contextlib import contextmanager
import errno
import gzip
import hashlib
from http.client import HTTPException
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
import tomllib
from urllib import request
from urllib.parse import urlsplit
from uuid import uuid4

from .catalog import ID
from .command_panels import CommandPanel, Processes
from .contract import valid_argv
from .paths import config_dir, data_dir
from .storage import atomic_write
from .text import clean

LIMIT = 16 * 1024 * 1024


def prefixes(key):
    return data_dir() / "packages" / key


def record(key):
    return config_dir() / "modules.d" / (key + ".toml")


@contextmanager
def exclusive():
    """The OS releases this advisory lock when the installer exits."""
    path = data_dir() / "modules.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ValueError("Başka bir modül işlemi sürüyor.") from exc
        yield


class AssetRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        url = urlsplit(newurl)
        if url.scheme != "https" or url.netloc not in ("github.com", "release-assets.githubusercontent.com",
                                                        "objects.githubusercontent.com"):
            raise ValueError("Paket yönlendirmesi geçersiz.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download(source):
    deadline = time.monotonic() + 60
    data = bytearray()
    with request.build_opener(AssetRedirect()).open(source, timeout=10) as response:
        while chunk := response.read1(65536):
            data.extend(chunk)
            if len(data) > LIMIT or time.monotonic() > deadline:
                raise ValueError("Paket indirme sınırı aşıldı.")
    return data


def manifest_version(data, executable):
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(data)) as compressed:
            raw = compressed.read(4 * LIMIT + 1)
        if len(raw) > 4 * LIMIT:
            raise ValueError("Açılmış paket çok büyük.")
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
            for member in archive:
                parts = member.name.split("/")
                if (not (member.isfile() or member.isdir()) or parts[0] != "package"
                        or any(part in ("", ".", "..", "node_modules") for part in parts)
                        or "\\" in member.name or ":" in member.name):
                    raise ValueError("Paket dosya listesi geçersiz.")
            manifest = json.load(archive.extractfile("package/package.json"))
        if any(manifest.get(k) for k in ("dependencies", "optionalDependencies", "peerDependencies",
                                         "bundledDependencies", "bundleDependencies")):
            raise ValueError("Yalnızca bağımlılıksız paketler destekleniyor.")
        if not isinstance(manifest["bin"], dict) or executable not in manifest["bin"] or not isinstance(manifest["version"], str):
            raise ValueError("Paket komutu veya sürümü geçersiz.")
        return manifest["version"]
    except (AttributeError, KeyError, TypeError, tarfile.TarError, EOFError, RecursionError) as exc:
        raise ValueError("Paket içeriği geçersiz.") from exc


def entry_from(row, key, processes):
    token = row["installation"]
    if not re.fullmatch("[0-9a-f]{32}", token) or not ID.fullmatch(key):
        raise ValueError("Geçersiz kurulum kimliği.")
    prefix = prefixes(key) / token
    panel, opening = row["panel"], row["open"]
    if not valid_argv(panel) or not valid_argv(opening) or panel[0] != opening[0] or not ID.fullmatch(panel[0]):
        raise ValueError("Geçersiz komut.")
    exe = prefix / (panel[0] + ".cmd") if os.name == "nt" else prefix / "bin" / panel[0]
    env = os.environ.copy()
    variable = row.get("data_file_env")
    if variable is not None:
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*_DATA_FILE", variable):
            raise ValueError("Geçersiz veri değişkeni.")
        env[variable] = str(data_dir() / "module-data" / key / "tasks.json")
    if not isinstance(row["title"], str) or not clean(row["title"]).strip():
        raise ValueError("Geçersiz başlık.")
    return CommandPanel(key, [str(exe), *panel[1:]], row["title"], [str(exe), *opening[1:]],
                        10, processes, env, True, variable)


def load_entries(entries, errors, processes):
    for path in (config_dir() / "modules.d").glob("*.toml"):
        try:
            if path.stem in entries:
                raise ValueError("Aynı kimlik elle yapılandırılmış.")
            row = tomllib.loads(path.read_text(encoding="utf8"))
            entries[path.stem] = entry_from(row, path.stem, processes)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            errors.append(f"{path.name}: {exc}")


def remove_empty_prefix(path):
    try:
        path.rmdir()
    except OSError as exc:
        if exc.errno not in (errno.ENOENT, errno.ENOTEMPTY, errno.EEXIST):
            raise


def install(item, runner):
    node, npm = shutil.which("node"), shutil.which("npm")
    if not node or not npm:
        raise ValueError("Node.js 20+ ve npm PATH üzerinde bulunmalı.")
    npm_cmd = [npm]
    if os.name == "nt":
        # Invoke npm through Node directly, including when the prefix has spaces.
        npm_cli = Path(npm).parent / "node_modules/npm/bin/npm-cli.js"
        if not npm_cli.is_file():
            raise ValueError(f"npm-cli.js bulunamadı: {npm_cli}. Standart bir Node.js kurulumu gerekir.")
        npm_cmd = [node, str(npm_cli)]
    version = subprocess.check_output([node, "--version"], text=True, timeout=5)
    if int(version.strip().lstrip("v").split(".")[0]) < 20:
        raise ValueError("Node.js 20+ gerekli.")
    path = record(item.id)
    with exclusive():
        if path.exists():
            raise ValueError("Modül kaydı zaten var.")
        try:
            data = download(item.source)
        except HTTPException as exc:
            raise ValueError("Paket indirilemedi.") from exc
        if hashlib.sha256(data).hexdigest() != item.sha256:
            raise ValueError("SHA-256 uyuşmuyor.")
        version = manifest_version(data, item.executable)
        token = uuid4().hex
        prefix = prefixes(item.id) / token
        prefix.mkdir(parents=True)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                archive = Path(tmp) / "package.tgz"
                archive.write_bytes(data)
                argv = [*npm_cmd, "install", "--global", "--prefix", str(prefix), "--ignore-scripts",
                        "--offline", "--no-audit", "--no-fund", str(archive)]
                if runner(argv, cwd=tmp).returncode:
                    raise ValueError("npm kurulumu başarısız.")
                row = dict(installation=token, version=version, title=item.title,
                           panel=[item.executable], open=[item.executable])
                if item.data_file_env:
                    row["data_file_env"] = item.data_file_env
                entry = entry_from(row, item.id, Processes())
                entry.argv.extend(["panel", "--describe"])
                descriptor = entry.read_json()
                if (not isinstance(descriptor, dict) or type(descriptor.get("format")) is not int
                        or descriptor["format"] != 1 or descriptor.get("id") != item.id
                        or descriptor.get("version") != version or descriptor.get("kind") != "command"):
                    raise ValueError("Modül tarifi katalogla uyuşmuyor.")
                for field in ("panel", "open"):
                    args = descriptor.get(field)
                    if not valid_argv(args) or args[0] != item.executable:
                        raise ValueError("Modül komutu katalogla uyuşmuyor.")
                row.update({k: descriptor.get(k) for k in ("title", "panel", "open")})
                entry_from(row, item.id, entry.processes)
                content = "".join(f"{k} = {json.dumps(v, ensure_ascii=False)}\n" for k, v in row.items())
                atomic_write(path, content.encode())
        except BaseException:
            shutil.rmtree(prefix)
            remove_empty_prefix(prefix.parent)
            raise


def remove(key, expected_program):
    path = record(key)
    with exclusive():
        row = tomllib.loads(path.read_text(encoding="utf8"))
        if entry_from(row, key, Processes()).argv[0] != expected_program:
            raise ValueError("Modül kaydı değişti; listeyi yenileyin.")
        prefix = prefixes(key) / row["installation"]
        # Unregister first: a crash during cleanup cannot expose a half-deleted panel.
        path.unlink()
        if prefix.exists():
            shutil.rmtree(prefix)
        remove_empty_prefix(prefix.parent)
        try:
            path.with_suffix(".lock").unlink(missing_ok=True)
        except OSError:
            pass
