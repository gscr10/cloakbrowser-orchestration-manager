from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from worker_backend import distributed_worker


@pytest.mark.asyncio
async def test_process_one_task_reports_success(monkeypatch):
    cfg = {"node_id": "worker-a"}
    browser_mgr = MagicMock()
    browser_mgr.running = {}

    pull_response = MagicMock()
    pull_response.raise_for_status = MagicMock()
    pull_response.json.return_value = {
        "task": {
            "id": "t1",
            "dispatch_id": "d1",
            "payload": {
                "profile_id": "p1",
                "authorized_target": "internal",
                "task_type": "external_cdp",
                "timeout_seconds": 300,
            },
        }
    }

    client = AsyncMock()
    client.post = AsyncMock(return_value=pull_response)

    monkeypatch.setattr(distributed_worker.scheduler, "submit_task", lambda payload: {"id": "local-1"})
    monkeypatch.setattr(distributed_worker.scheduler, "tick", AsyncMock())
    monkeypatch.setattr(distributed_worker.db, "get_task", lambda task_id: {"id": task_id, "status": "running"})

    processed = await distributed_worker.process_one_task(client, cfg, browser_mgr)
    assert processed is True
    calls = client.post.await_args_list
    assert calls[1].args[0] == "/api/master/tasks/t1/report"
    assert calls[2].kwargs["json"]["status"] == "success"


@pytest.mark.asyncio
async def test_process_one_task_reports_failure_when_profile_missing(monkeypatch):
    cfg = {"node_id": "worker-a"}
    browser_mgr = MagicMock()
    browser_mgr.running = {}

    pull_response = MagicMock()
    pull_response.raise_for_status = MagicMock()
    pull_response.json.return_value = {
        "task": {
            "id": "t2",
            "dispatch_id": "d2",
            "payload": {
                "authorized_target": "internal",
                "task_type": "external_cdp",
            },
        }
    }

    client = AsyncMock()
    client.post = AsyncMock(return_value=pull_response)

    processed = await distributed_worker.process_one_task(client, cfg, browser_mgr)
    assert processed is True
    fail_call = client.post.await_args_list[-1]
    assert fail_call.kwargs["json"]["status"] == "failed"


def test_collect_resource_snapshot(monkeypatch, tmp_path):
    meminfo = tmp_path / "meminfo"
    meminfo.write_text("MemTotal:       1024000 kB\nMemAvailable:    512000 kB\n", encoding="utf-8")
    monkeypatch.setattr(distributed_worker, "_MEMINFO_PATH", meminfo)
    monkeypatch.setattr(distributed_worker.os, "getloadavg", lambda: (1.0, 1.0, 1.0))
    monkeypatch.setattr(distributed_worker.os, "cpu_count", lambda: 2)

    snap = distributed_worker.collect_resource_snapshot()
    assert snap["mem_total_mb"] == 1000
    assert snap["mem_used_mb"] == 500
    assert isinstance(snap["cpu_percent"], float)
