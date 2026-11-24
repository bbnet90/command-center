from importlib import metadata
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from command_center.check import check
from command_center.cli import main
from command_center.contract import validate
from command_center.paths import config_dir
from command_center.plugins import conflicts, discover


def entry(key, package, load):
    return SimpleNamespace(name=key, dist=SimpleNamespace(name=package), load=load)


def test_conflict_and_config_order(monkeypatch, capsys):
    entries = [entry("p", name, lambda n=name: lambda: {"title": n, "lines": []})
               for name in ("ZZ", "a-B")]
    config_dir().mkdir(parents=True)
    (config_dir() / "config.toml").write_text('panels=["p","p"]')
    monkeypatch.setattr(metadata, "entry_points", lambda **kw: entries)
    for _ in range(2):
        entries.reverse()
        assert discover()["p"].dist.name == "a-B"
        assert conflicts() == {"p": ["a-B", "ZZ"]}
    main()
    assert capsys.readouterr().out.count("a-B") == 1
    assert main(["check", "p"]) == 0
    assert "Giriş noktası çakışması: p · a-B, ZZ" in capsys.readouterr().out


def test_bounds_and_extra_fields():
    value = {"title": "Good", "lines": ["a"*300]*100, "future": None}
    assert validate(value) == {"title": "Good", "lines": value["lines"]}
    value["lines"].append("excess")
    result = validate(value)["lines"]
    assert len(result) == 100 and result[-1] == "… (kısaltıldı)"
    value["lines"] = ["a"*301]
    assert validate(value)["lines"] == ["a"*300, "… (kısaltıldı)"]
    value["lines"] = ["ok"]*101 + [None]
    with pytest.raises(ValueError):
        validate(value)


def test_capture_and_width(monkeypatch, capsys):
    def load():
        print("during import")

        def provide():
            print("[red]message", file=sys.stderr)
            return {"title": "Example", "lines": ["界"*24]}
        return provide
    monkeypatch.setattr(metadata, "entry_points", lambda **kw: [entry("wide", "pkg", load)])
    main()
    dashboard = capsys.readouterr()
    assert "during import" not in dashboard.out and not dashboard.err
    assert main(["check"]) == 0
    report = capsys.readouterr()
    assert not report.err
    for word in ("wide · pkg · OK", "ms", "1 satır", "en geniş: 48", "46 sütunu",
                 "stdout", "during import", "stderr", "[red]message"):
        assert word in report.out


def test_failed_checks_and_suggestion(monkeypatch, capsys):
    def broken():
        raise RuntimeError("details")

    entries = [entry("raising", "one", lambda: broken),
               entry("invalid", "two", lambda: lambda: {"title": "T", "lines": 13})]
    monkeypatch.setattr(metadata, "entry_points", lambda **kw: entries)
    assert main(["check"]) == 1
    report = capsys.readouterr().out
    assert report.count("FAIL") == 2
    assert "RuntimeError: details" in report and "lines yalnızca metin" in report
    assert main(["check", "raisin"]) == 1
    assert "Benzer kimlikler: raising" in capsys.readouterr().out


@pytest.mark.parametrize(("writes", "child_code"), [(False, 0), (True, 0), (False, 1)])
def test_isolated_runner(writes, child_code, capsys):
    dirs = []

    def runner(argv, *, env, cwd):
        assert argv[:-1] == [sys.executable, "-m", "command_center", "check"]
        assert argv[-1] in ("a", "b")
        path = Path(cwd)
        assert list(path.iterdir()) == []
        for name in ("HOME", "XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME"):
            assert env[name] == cwd
        dirs.append(path)
        if writes:
            (path / "sub").mkdir()
            (path / "sub/db").touch()
        return SimpleNamespace(returncode=child_code)

    assert check(dict.fromkeys(["a", "b"]), isolated=True, runner=runner) == int(writes or child_code)
    assert len(set(dirs)) == 2 and all(not p.exists() for p in dirs)
    if writes:
        assert capsys.readouterr().out.count("panel dosya oluşturdu: sub, sub/db") == 2


def test_provider_closes_stream(monkeypatch, capsys):
    def provider():
        print("captured")
        sys.stdout.close()
        raise RuntimeError("stopped")

    monkeypatch.setattr(metadata, "entry_points", lambda **kw: [entry("p", "pkg", lambda: provider)])
    assert main() == 0
    assert "captured" not in capsys.readouterr().out
    assert main(["check"]) == 1
    output = capsys.readouterr().out
    assert "captured" in output and "stopped" in output
