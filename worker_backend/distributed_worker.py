"""Worker-side pull/execute/report loop for distributed mode."""

from __future__ import annotations

import asyncio
import logging
import os
import socket
from pathlib import Path
from typing import Any

import httpx

from . import database as db
from . import scheduler
from .browser_manager import BrowserManager

logger = logging.getLogger("cloakbrowser.worker")
_MEMINFO_PATH = Path("/proc/meminfo")


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def enabled() -> bool:
    return _env_bool("DISTRIBUTED_WORKER_ENABLED", False)


def settings() -> dict[str, Any]:
    api_port = int(os.environ.get("WORKER_API_PORT", "8080"))
    api_base = os.environ.get("WORKER_API_BASE") or f"http://127.0.0.1:{api_port}"
    return {
        "master_url": os.environ.get("MASTER_BASE_URL", "http://127.0.0.1:8080").rstrip("/"),
        "node_id": os.environ.get("WORKER_NODE_ID", socket.gethostname()),
        "hostname": os.environ.get("WORKER_HOSTNAME", socket.gethostname()),
        "api_base": api_base.rstrip("/"),
        "poll_interval": float(os.environ.get("WORKER_POLL_INTERVAL_SECONDS", "5")),
        "heartbeat_interval": float(os.environ.get("WORKER_HEARTBEAT_INTERVAL_SECONDS", "5")),
        "max_profiles": int(os.environ.get("MAX_RUNNING_PROFILES", "15") if os.environ.get("MAX_RUNNING_PROFILES", "15").isdigit() else 15),
        "token": os.environ.get("AUTH_TOKEN") or os.environ.get("CLOAK_MANAGER_TOKEN"),
    }


async def register_node(client: httpx.AsyncClient, cfg: dict[str, Any]) -> None:
    await client.post(
        "/api/master/nodes/register",
        json={
            "node_id": cfg["node_id"],
            "hostname": cfg["hostname"],
            "api_base": cfg.get("api_base"),
            "max_profiles": cfg["max_profiles"],
        },
    )


async def send_heartbeat(client: httpx.AsyncClient, cfg: dict[str, Any], browser_mgr: BrowserManager) -> None:
    snapshot = collect_resource_snapshot()
    await client.post(
        "/api/master/nodes/heartbeat",
        json={
            "node_id": cfg["node_id"],
            "running_profiles": len(browser_mgr.running),
            "cpu_percent": snapshot.get("cpu_percent"),
            "mem_total_mb": snapshot.get("mem_total_mb"),
            "mem_used_mb": snapshot.get("mem_used_mb"),
            "status": "online",
        },
    )


def collect_resource_snapshot() -> dict[str, int | float | None]:
    cpu_percent = None
    try:
        load1 = os.getloadavg()[0]
        cpus = os.cpu_count() or 1
        cpu_percent = max(0.0, min(100.0, (load1 / cpus) * 100.0))
    except Exception:
        cpu_percent = None

    mem_total_mb = None
    mem_used_mb = None
    try:
        mem = _read_meminfo_kib()
        total = mem.get("MemTotal", 0)
        available = mem.get("MemAvailable", 0)
        if total > 0:
            used = max(0, total - available)
            mem_total_mb = int(total // 1024)
            mem_used_mb = int(used // 1024)
    except Exception:
        mem_total_mb = None
        mem_used_mb = None

    return {
        "cpu_percent": cpu_percent,
        "mem_total_mb": mem_total_mb,
        "mem_used_mb": mem_used_mb,
    }


def _read_meminfo_kib() -> dict[str, int]:
    values: dict[str, int] = {}
    for line in _MEMINFO_PATH.read_text(encoding="utf-8").splitlines():
        if ":" not in line:
            continue
        key, raw = line.split(":", 1)
        number = raw.strip().split(" ", 1)[0]
        if number.isdigit():
            values[key] = int(number)
    return values


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
            }
        )
        await scheduler.tick(browser_mgr, task_id=local_task["id"])
        latest = db.get_task(local_task["id"])
        if not latest or latest.get("status") in {"queued", "failed"}:
            reason = latest.get("failure_reason") if latest else "local task missing"
            await client.post(
                f"/api/master/tasks/{task_id}/report",
                json={
                    "node_id": cfg["node_id"],
                    "status": "failed",
                    "dispatch_id": dispatch_id,
                    "failure_reason": reason or "local task failed",
                },
            )
        else:
            await client.post(
                f"/api/master/tasks/{task_id}/report",
                json={"node_id": cfg["node_id"], "status": "success", "dispatch_id": dispatch_id},
            )
    except Exception as exc:
        await client.post(
            f"/api/master/tasks/{task_id}/report",
            json={
                "node_id": cfg["node_id"],
                "status": "failed",
                "dispatch_id": dispatch_id,
                "failure_reason": str(exc),
            },
        )
    return True


async def worker_loop(browser_mgr: BrowserManager) -> None:
    cfg = settings()
    headers = {"Authorization": f"Bearer {cfg['token']}"} if cfg.get("token") else None
    heartbeat_every = max(1.0, float(cfg["heartbeat_interval"]))
    poll_interval = max(0.5, float(cfg["poll_interval"]))
    last_heartbeat = 0.0

    async with httpx.AsyncClient(base_url=cfg["master_url"], headers=headers, timeout=15.0) as client:
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
