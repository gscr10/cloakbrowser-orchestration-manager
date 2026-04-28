"""Single-node task scheduler built on top of BrowserManager.

This layer deliberately reuses BrowserManager for all CloakBrowser, VNC, CDP,
and persistent profile handling. It only adds queueing and proxy assignment.
"""

from __future__ import annotations

import os
from typing import Any

from . import database as db
from .browser_manager import BrowserManager


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


def max_running_profiles() -> int:
    return int(os.environ.get("MAX_RUNNING_PROFILES", "3"))


def submit_task(payload: dict[str, Any]) -> dict[str, Any]:
    text = " ".join(str(value) for value in payload.values()).lower()
    if any(term in text for term in PROHIBITED_TERMS):
        raise PolicyDenied("task is outside the allowed automation policy")
    if not db.get_profile(payload["profile_id"]):
        raise KeyError("Profile not found")
    return db.create_task(**payload)


async def tick(browser_mgr: BrowserManager) -> dict[str, Any]:
    """Start the next queued task if local capacity allows it."""
    if len(browser_mgr.running) >= max_running_profiles():
        return scheduler_status(browser_mgr)

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
        if task["task_type"] == "open_url" and task.get("url"):
            page = running.context.pages[0] if running.context.pages else await running.context.new_page()
            await page.goto(task["url"], wait_until="domcontentloaded", timeout=task["timeout_seconds"] * 1000)
        db.update_profile_run(run["id"], status="running")
    except Exception as exc:
        db.update_task(task["id"], status="failed", failure_reason=str(exc))
        db.update_profile_run(run["id"], status="failed", stopped_at=db._now(), failure_reason=str(exc))
        raise

    return scheduler_status(browser_mgr)


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
