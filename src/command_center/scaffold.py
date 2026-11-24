from importlib import resources
from pathlib import Path
import shlex

from .catalog import ID
from .rendering import line


def create(key: str, directory=None) -> int:
    if not ID.fullmatch(key):
        line("Geçersiz modül kimliği.")
        return 2
    default = f"command-center-{key}"
    root = Path(directory) if directory is not None else Path(default)
    # Distribution names must end in a letter or digit. Entry point IDs need not.
    project = default if key[-1].isalnum() else default + "panel"
    package = "command_center_" + key.replace("-", "_")
    templates = resources.files("command_center").joinpath("data", "templates")
    files = {
        "pyproject.toml": "project.toml.tmpl",
        f"src/{package}/__init__.py": None,
        f"src/{package}/panel.py": "panel.py.tmpl",
        "tests/test_panel.py": "test_panel.py.tmpl",
        "README.md": "README.md.tmpl",
        ".gitignore": "gitignore.tmpl",
        ".github/workflows/tests.yml": "tests.yml.tmpl",
    }
    try:
        root.mkdir(parents=True)
    except FileExistsError:
        line(f"Hedef zaten var: {root}")
        return 1
    except OSError as exc:
        line(f"Hedef oluşturulamadı: {exc}")
        return 1
    created = [root]
    try:
        for path, template in files.items():
            content = templates.joinpath(template).read_text(encoding="utf-8") if template else ""
            content = content.replace("{id}", key).replace("{package}", package).replace("{project}", project)
            target = root / path
            for parent in reversed(target.parents):
                if root in parent.parents and not parent.exists():
                    parent.mkdir()
                    created.append(parent)
            with target.open("x", encoding="utf-8") as stream:
                created.append(target)
                stream.write(content)
    except OSError as exc:
        for path in reversed(created):
            try:
                path.rmdir() if path.is_dir() else path.unlink()
            except OSError:
                pass
        line(f"Proje oluşturulamadı: {exc}")
        return 1
    line("Sonraki adımlar:")
    line(shlex.join(["cd", str(root.resolve())]), plain=True)
    line("pip install -e .", plain=True)
    line(f"command-center check {key} --isolated", plain=True)
    line("Paketi yayımladıktan sonra catalog.toml dosyasına ekleyin:")
    for row in ('[[module]]', f'id = "{key}"', f'title = "{key}"',
                'description = "Panelin kısa açıklaması."', 'kind = "panel"',
                f'source = "{project}"'):
        line(row, plain=True)
    return 0
