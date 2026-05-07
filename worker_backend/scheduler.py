"""Single-node task scheduler built on top of BrowserManager.

This layer deliberately reuses BrowserManager for all CloakBrowser, VNC, CDP,
and persistent profile handling. It only adds queueing and proxy assignment.
"""

from __future__ import annotations

from typing import Any

from . import database as db
from . import profile_runtime
from .browser_manager import BrowserManager
from .runtime_limits import max_running_profiles


PROHIBITED_TERMS = (
    "captcha",
    "credential stuffing",
    "bulk signup",
    "account takeover",
    "spam",
    "bruteforce",
)


class PolicyDenied(ValueError):
    """Raised when a submitted task does not meet local safety policy."""


def submit_task(payload: dict[str, Any]) -> dict[str, Any]:
    text = " ".join(str(value) for value in payload.values()).lower()
    if any(term in text for term in PROHIBITED_TERMS):
        raise PolicyDenied("task is outside the allowed automation policy")
    if not db.get_profile(payload["profile_id"]):
        raise KeyError("Profile not found")
    return db.create_task(**payload)


async def tick(browser_mgr: BrowserManager, task_id: str | None = None) -> dict[str, Any]:
    """Start the next queued task if local capacity allows it."""
    if len(browser_mgr.running) >= max_running_profiles():
        return scheduler_status(browser_mgr)

    if task_id:
        task = db.get_task(task_id)
        if task and task.get("status") != "queued":
            return scheduler_status(browser_mgr)
    else:
        task = db.next_queued_task()
    if not task:
        return scheduler_status(browser_mgr)

    profile = db.get_profile(task["profile_id"])
    if not profile:
        db.update_task(task["id"], status="failed", failure_reason="profile not found")
        return scheduler_status(browser_mgr)
    if profile["id"] in browser_mgr.running:
        db.update_task(task["id"], status="failed", failure_reason="profile is already running")
        return scheduler_status(browser_mgr)

    proxy = db.select_proxy_endpoint()
    runtime_profile = dict(profile)
    if proxy:
        runtime_profile["proxy"] = proxy_url(proxy)

    run = db.create_profile_run(
        profile_id=profile["id"],
        task_id=task["id"],
        proxy_id=proxy["id"] if proxy else None,
        status="starting",
    )
    db.update_task(task["id"], status="running", proxy_id=proxy["id"] if proxy else None, run_id=run["id"])

    try:
        running = await browser_mgr.launch(runtime_profile)
        result = await profile_runtime.execute_task(running, task)
        latest = db.get_task(task["id"])
        if latest and latest.get("status") == "cancelled":
            db.update_profile_run(run["id"], status="cancelled", stopped_at=db._now(), failure_reason=latest.get("failure_reason"))
            return scheduler_status(browser_mgr)
        if task["task_type"] in {"open_url", "automation_script"}:
            payload = dict(task.get("payload") or {})
            if result:
                payload["result"] = result
            db.update_task(task["id"], status="success", payload=payload)
        db.update_profile_run(run["id"], status="running")
    except Exception as exc:
        latest = db.get_task(task["id"])
        if latest and latest.get("status") == "cancelled":
            db.update_profile_run(run["id"], status="cancelled", stopped_at=db._now(), failure_reason=latest.get("failure_reason") or str(exc))
            return scheduler_status(browser_mgr)
        payload = dict(task.get("payload") or {})
        result = getattr(exc, "result", None)
        if isinstance(result, dict) and result:
            payload["result"] = result
        db.update_task(task["id"], status="failed", failure_reason=str(exc), payload=payload)
        db.update_profile_run(run["id"], status="failed", stopped_at=db._now(), failure_reason=str(exc))
        raise

    return scheduler_status(browser_mgr)


async def cancel_task(browser_mgr: BrowserManager, task_id: str, reason: str = "cancelled by operator") -> dict[str, Any] | None:
    """Cancel a queued or running local task and stop its browser profile."""
    task = db.get_task(task_id)
    if not task:
        return None
    if task["status"] not in {"queued", "running"}:
        return task
    updated = db.update_task(task_id, status="cancelled", failure_reason=reason)
    if task["status"] == "running":
        if task.get("run_id"):
            db.update_profile_run(task["run_id"], status="cancelled", stopped_at=db._now(), failure_reason=reason)
        await browser_mgr.stop(task["profile_id"])
    return updated


async def cancel_distributed_task(browser_mgr: BrowserManager, master_task_id: str, reason: str = "cancelled by master") -> dict[str, Any] | None:
    """Cancel a local task that was created for a pulled Master task."""
    for task in db.list_tasks():
        payload = task.get("payload") or {}
        if payload.get("master_task_id") == master_task_id:
            return await cancel_task(browser_mgr, task["id"], reason=reason)
    return None


def scheduler_status(browser_mgr: BrowserManager) -> dict[str, int]:
    queued_count = len([task for task in db.list_tasks() if task["status"] == "queued"])
    return {
        "queued_count": queued_count,
        "running_count": len(browser_mgr.running),
        "max_running": max_running_profiles(),
    }


def proxy_url(proxy: dict[str, Any]) -> str:
    auth = ""
    if proxy.get("username"):
        password = proxy.get("password") or ""
        auth = f"{proxy['username']}:{password}@"
    return f"{proxy['protocol']}://{auth}{proxy['host']}:{proxy['port']}"