import pytest


@pytest.fixture(autouse=True)
def isolated_xdg(tmp_path, monkeypatch):
    for name in ("CONFIG", "CACHE", "STATE"):
        monkeypatch.setenv(f"XDG_{name}_HOME", str(tmp_path / name))


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    import socket

    def blocked(*args, **kwargs):
        pytest.fail("Unexpected network request")

    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)
