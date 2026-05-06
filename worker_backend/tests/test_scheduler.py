from __future__ import annotations

from unittest.mock import AsyncMock

from worker_backend import database as db
from worker_backend import scheduler


class FakeBrowserManager:
    def __init__(self) -> None:
        self.running = {}
        self.launch = AsyncMock(return_value=object())


async def test_open_url_task_marks_success(tmp_db, monkeypatch):
    profile = db.create_profile("Open URL")
    task = db.create_task(
        profile_id=profile["id"],
        authorized_target="internal test app",
        task_type="open_url",
        url="https://example.com",
        timeout_seconds=300,
    )
    monkeypatch.setattr(
        scheduler.profile_runtime,
        "execute_task",
        AsyncMock(return_value={"url": "https://example.com", "title": "Example"}),
    )

    await scheduler.tick(FakeBrowserManager(), task_id=task["id"])

    latest = db.get_task(task["id"])
    assert latest is not None
    assert latest["status"] == "success"
    assert latest["payload"]["result"] == {"url": "https://example.com", "title": "Example"}
