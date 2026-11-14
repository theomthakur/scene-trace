import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("VI_DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data"


@pytest.fixture()
def client(data_dir):
    from video_investigator.api.app import create_app
    with TestClient(create_app()) as c:
        yield c
