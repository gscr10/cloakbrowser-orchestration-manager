"""Worker-side pull/execute/report loop for distributed mode."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from . import database as db
from . import infra_agent
from . import scheduler
from .browser_manager import BrowserManager

logger = logging.getLogger("cloakbrowser.worker")
enabled = infra_agent.enabled
settings = infra_agent.settings
register_node = infra_agent.register_node
send_heartbeat = infra_agent.send_heartbeat
collect_resource_snapshot = infra_agent.collect_resource_snapshot


async def process_one_task(client: httpx.AsyncClient, cfg: dict[str, Any], browser_mgr: BrowserManager) -> bool:
    pull = await client.post("/api/master/tasks/pull", json={"node_id": cfg["node_id"]})
    pull.raise_for_status()
    task = pull.json().get("task")
    if not task:
        return False

    task_id = task["id"]
    dispatch_id = task.get("dispatch_id")
    payload = task.get("payload") or {}
    await client.post(
        f"/api/master/tasks/{task_id}/report",
        json={"node_id": cfg["node_id"], "status": "started", "dispatch_id": dispatch_id},
    )

    local_task: dict[str, Any] | None = None
    try:
        profile_id = payload.get("profile_id")
        if not profile_id:
            raise ValueError("missing profile_id")
        local_task = scheduler.submit_task(
            {
                "profile_id": profile_id,
                "authorized_target": payload.get("authorized_target", "internal task"),
                "task_type": payload.get("task_type", "external_cdp"),
                "url": payload.get("url"),
                "timeout_seconds": int(payload.get("timeout_seconds") or 300),
                "payload": payload,
            }
        )
        await scheduler.tick(browser_mgr, task_id=local_task["id"])
        latest = db.get_task(local_task["id"])
        if not latest or latest.get("status") in {"queued", "failed"}:
            reason = latest.get("failure_reason") if latest else "local task missing"
            result = {}
            if latest and isinstance(latest.get("payload"), dict):
                result = latest["payload"].get("result") or {}
            await client.post(
                f"/api/master/tasks/{task_id}/report",
                json={
                    "node_id": cfg["node_id"],
                    "status": "failed",
                    "dispatch_id": dispatch_id,
                    "failure_reason": reason or "local task failed",
                    "result": result,
                },
            )
        else:
            result = {}
            if isinstance(latest.get("payload"), dict):
                result = latest["payload"].get("result") or {}
            await client.post(
                f"/api/master/tasks/{task_id}/report",
                json={"node_id": cfg["node_id"], "status": "success", "dispatch_id": dispatch_id, "result": result},
            )
    except Exception as exc:
        result = {}
        if local_task:
            latest = db.get_task(local_task["id"])
            if latest and isinstance(latest.get("payload"), dict):
                result = latest["payload"].get("result") or {}
        await client.post(
            f"/api/master/tasks/{task_id}/report",
            json={
                "node_id": cfg["node_id"],
                "status": "failed",
                "dispatch_id": dispatch_id,
                "failure_reason": str(exc),
                "result": result,
            },
        )
    return True


async def worker_loop(browser_mgr: BrowserManager) -> None:
    cfg = settings()
    heartbeat_every = max(1.0, float(cfg["heartbeat_interval"]))
    poll_interval = max(0.5, float(cfg["poll_interval"]))
    last_heartbeat = 0.0

    async with httpx.AsyncClient(base_url=cfg["master_url"], timeout=15.0) as client:
        while True:
            try:
                await register_node(client, cfg)
                now = asyncio.get_running_loop().time()
                if now - last_heartbeat >= heartbeat_every:
                    await send_heartbeat(client, cfg, browser_mgr)
                    last_heartbeat = now
                processed = await process_one_task(client, cfg, browser_mgr)
                await asyncio.sleep(0.2 if processed else poll_interval)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Distributed worker loop iteration failed: %s", exc)
                await asyncio.sleep(poll_interval)
