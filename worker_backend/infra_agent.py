from __future__ import annotations

import os
import socket
from pathlib import Path
from typing import Any

import httpx

from .automation import list_templates
from .browser_manager import BrowserManager

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
    tags = [item.strip() for item in os.environ.get("WORKER_TAGS", "").split(",") if item.strip()]
    return {
        "master_url": os.environ.get("MASTER_BASE_URL", "http://127.0.0.1:8080").rstrip("/"),
        "node_id": os.environ.get("WORKER_NODE_ID", socket.gethostname()),
        "hostname": os.environ.get("WORKER_HOSTNAME", socket.gethostname()),
        "api_base": api_base.rstrip("/"),
        "tags": tags,
        "poll_interval": float(os.environ.get("WORKER_POLL_INTERVAL_SECONDS", "5")),
        "heartbeat_interval": float(os.environ.get("WORKER_HEARTBEAT_INTERVAL_SECONDS", "5")),
        "max_profiles": int(os.environ.get("MAX_RUNNING_PROFILES", "15") if os.environ.get("MAX_RUNNING_PROFILES", "15").isdigit() else 15),
    }


async def register_node(client: httpx.AsyncClient, cfg: dict[str, Any]) -> None:
    await client.post(
        "/api/master/nodes/register",
        json={
            "node_id": cfg["node_id"],
            "hostname": cfg["hostname"],
            "api_base": cfg.get("api_base"),
            "tags": cfg.get("tags") or [],
            "max_profiles": cfg["max_profiles"],
            "capabilities": list_templates(),
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
            "profiles": collect_profile_snapshot(browser_mgr),
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


def collect_profile_snapshot(browser_mgr: BrowserManager) -> list[dict[str, Any]]:
    profiles = []
    for profile_id, running in browser_mgr.running.items():
        profiles.append(
            {
                "profile_id": profile_id,
                "status": "running",
                "vnc_ws_port": running.ws_port,
                "cdp_port": running.cdp_port,
                "display": str(running.display),
            }
        )
    return profiles


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
