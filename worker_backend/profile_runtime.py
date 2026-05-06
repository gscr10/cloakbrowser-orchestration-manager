from __future__ import annotations

from typing import Any

from . import automation_runtime
from .browser_manager import RunningProfile


async def execute_task(running: RunningProfile, task: dict[str, Any]) -> dict[str, Any] | None:
    """Run the profile-level action after the browser has launched.

    Scheduler owns queueing and profile slot decisions; this module owns
    browser/profile execution semantics.
    """
    if task["task_type"] == "open_url" and task.get("url"):
        page = running.context.pages[0] if running.context.pages else await running.context.new_page()
        await page.goto(task["url"], wait_until="domcontentloaded", timeout=task["timeout_seconds"] * 1000)
        return {"url": page.url, "title": await page.title()}

    if task["task_type"] == "automation_script":
        payload = dict(task.get("payload") or {})
        payload.setdefault("url", task.get("url"))
        payload.setdefault("authorized_target", task.get("authorized_target"))
        payload.setdefault("timeout_seconds", task.get("timeout_seconds"))
        return await automation_runtime.run_template(running, payload)

    return None
