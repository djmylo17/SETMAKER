import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    d = tmp_path / "data"
    monkeypatch.setenv("SETMAKER_DATA_DIR", str(d))
    from app.paths import data_dir as dd
    return dd()
