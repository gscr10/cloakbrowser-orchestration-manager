"""Tests for external Docker config imports."""

from __future__ import annotations

import json
from pathlib import Path

from worker_backend import config_importer
from worker_backend import database as db


def test_import_profiles_json_creates_and_updates_by_name(tmp_db: Path, tmp_path: Path):
    profiles_path = tmp_path / "profiles.json"
    profiles_path.write_text(json.dumps({
        "profiles": [
            {
                "name": "worker-1",
                "fingerprint_seed": 12345,
                "platform": "linux",
                "proxy": "http://proxy.test:8080",
                "tags": [{"tag": "automation"}],
            }
        ]
    }), encoding="utf-8")

    first = config_importer.import_profiles_json(profiles_path)
    assert len(first["created"]) == 1
    assert first["updated"] == []
    profile_id = first["created"][0]["id"]

    profiles_path.write_text(json.dumps([
        {
            "name": "worker-1",
            "fingerprint_seed": 12345,
            "platform": "linux",
            "proxy": "http://proxy2.test:8080",
            "timezone": "America/New_York",
        }
    ]), encoding="utf-8")
    second = config_importer.import_profiles_json(profiles_path)

    assert second["created"] == []
    assert len(second["updated"]) == 1
    assert second["updated"][0]["id"] == profile_id
    assert second["updated"][0]["proxy"] == "http://proxy2.test:8080"
    assert db.get_profile(profile_id)["timezone"] == "America/New_York"


def test_import_profiles_json_reports_invalid_entries(tmp_db: Path, tmp_path: Path):
    profiles_path = tmp_path / "profiles.json"
    profiles_path.write_text(json.dumps([{"platform": "linux"}, "bad"]), encoding="utf-8")

    result = config_importer.import_profiles_json(profiles_path)

    assert result["created"] == []
    assert len(result["errors"]) == 2


def test_import_proxies_csv_is_idempotent(tmp_db: Path, tmp_path: Path):
    proxies_path = tmp_path / "proxies.csv"
    proxies_path.write_text("protocol,host,port\nhttp,proxy.test,8080\n", encoding="utf-8")

    first = config_importer.import_proxies_csv(proxies_path)
    second = config_importer.import_proxies_csv(proxies_path)

    assert len(first["created"]) == 1
    assert first["skipped"] == []
    assert second["created"] == []
    assert second["skipped"] == [{"line": 2, "error": "duplicate proxy endpoint"}]
    assert second["errors"] == []


def test_import_config_dir_imports_supported_files(tmp_db: Path, tmp_path: Path):
    (tmp_path / "profiles.json").write_text(json.dumps([{"name": "worker-1"}]), encoding="utf-8")
    (tmp_path / "proxies.csv").write_text("protocol,host,port\nhttp,proxy.test,8080\n", encoding="utf-8")

    result = config_importer.import_config_dir(tmp_path)

    assert result["config_dir"] == str(tmp_path)
    assert len(result["profiles"]["created"]) == 1
    assert len(result["proxies"]["created"]) == 1
