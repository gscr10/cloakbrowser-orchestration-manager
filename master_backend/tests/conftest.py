from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture()
def master_app_client(tmp_path: Path):
    from master_backend import database as master_db
    from master_backend import main as master_main
    from starlette.testclient import TestClient

    master_db.DB_PATH = tmp_path / "master.db"
    master_db.DATA_DIR = tmp_path
    master_db.init_db()

    with TestClient(master_main.app) as client:
        yield client
