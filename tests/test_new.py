from pathlib import Path
import subprocess
import sys
import tomllib

import pytest

from command_center.catalog import parse
from command_center.cli import main


def test_scaffold(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["new", "sample-id"]) == 0
    root = Path("command-center-sample-id")
    files = {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}
    assert files == {"pyproject.toml", "README.md", ".gitignore", ".github/workflows/tests.yml",
                     "src/command_center_sample_id/__init__.py", "src/command_center_sample_id/panel.py",
                     "tests/test_panel.py"}
    project = tomllib.loads((root / "pyproject.toml").read_text())["project"]
    assert project["dependencies"] == [] and project["requires-python"] == ">=3.11"
    assert project["entry-points"]["command_center.panels"] == {
        "sample-id": "command_center_sample_id.panel:panel"}
    report = capsys.readouterr().out
    assert "pip install -e ." in report and "command-center check sample-id --isolated" in report
    catalog, dropped = parse(("format = 1\n" + report[report.index("[[module]]"):]).encode())
    assert dropped == 0 and catalog["sample-id"].source == project["name"]
    subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=root, check=True)


@pytest.mark.parametrize("existing", ["directory", "file", "symlink"])
def test_refuse_existing(tmp_path, existing):
    path = tmp_path / "here"
    if existing == "directory":
        path.mkdir()
    elif existing == "file":
        path.write_text("keep")
    else:
        path.symlink_to(tmp_path / "absent")
    assert main(["new", "a", "--dir", str(path)]) == 1
    if existing == "directory":
        assert not list(path.iterdir())
    elif existing == "file":
        assert path.read_text() == "keep"
    else:
        assert path.is_symlink() and not path.exists()


def test_custom_directory_and_invalid_id(tmp_path):
    dest = tmp_path / "custom"
    assert main(["new", "../bad", "--dir", str(dest)]) == 2 and not dest.exists()
    assert main(["new", "3-a-", "--dir", str(dest)]) == 0
    assert (dest / "src/command_center_3_a_/panel.py").is_file()
