import pytest

from app.config import load_config


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("OUT_DIR", str(tmp_path / "out"))
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    return load_config()
