from __future__ import annotations

import datetime as dt
import os
from typing import Any
from urllib.parse import urlparse

from . import database as db
from . import infra_repository as repo


def _parse_ts(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value)
    except ValueError:
        return None


def find_available_worker(
    worker_tags: list[str] | None = None,
    required_capabilities: list[dict[str, str]] | None = None,
    heartbeat_ttl_seconds: int = 30,
) -> dict[str, Any] | None:
    """Infrastructure scheduling contract used by business code.

    Business callers describe what they need; only this layer knows how to
    interpret node health, resource pressure, profile slots, tags, and
    capabilities.
    """
    worker_tags = worker_tags or []
    required_capabilities = required_capabilities or []
    max_running_per_script = int(os.environ.get("MASTER_MAX_RUNNING_PER_SCRIPT_PER_NODE", "0") or 0)
    capabilities = repo.list_capabilities()
    by_node = {}
    for cap in capabilities:
        by_node.setdefault(cap["node_id"], set()).add((cap["script_key"], cap["script_version"]))
    active_counts: dict[str, int] = {}
    for task in db.list_master_tasks():
        node_id = task.get("target_node_id")
        if node_id and task.get("status") in {"queued", "dispatched", "running"}:
            active_counts[str(node_id)] = active_counts.get(str(node_id), 0) + 1

    candidates = []
    now = dt.datetime.now(dt.timezone.utc)
    for node in db.list_master_nodes():
        if node["status"] != "online":
            continue
        hb = _parse_ts(node.get("last_heartbeat_at"))
        if hb and (now - hb).total_seconds() > heartbeat_ttl_seconds:
            continue
        running_profiles = int(node.get("running_profiles") or 0)
        max_profiles = int(node.get("max_profiles") or 15)
        reserved_profiles = active_counts.get(node["node_id"], 0)
        effective_profiles = running_profiles + reserved_profiles
        if effective_profiles >= max_profiles:
            continue
        cpu = float(node.get("cpu_percent") or 0.0)
        mem_total = int(node.get("mem_total_mb") or 0)
        mem_used = int(node.get("mem_used_mb") or 0)
        mem_ratio = (mem_used / mem_total) if mem_total > 0 else 0.0
        if cpu > 95.0 or mem_ratio > 0.95:
            continue
        infra_worker = repo.get_worker(node["node_id"])
        if infra_worker:
            if not infra_worker.get("enabled", True):
                continue
            if infra_worker.get("desired_state") != "active":
                continue
        node_tags = set(node.get("tags") or [])
        if infra_worker:
            node_tags.update(infra_worker.get("tags") or [])
        if worker_tags and not set(worker_tags).issubset(node_tags):
            continue
        node_caps = by_node.get(node["node_id"], set())
        for cap in required_capabilities:
            required = (cap.get("script_key") or "", cap.get("script_version") or "")
            if required not in node_caps:
                break
        else:
            if max_running_per_script and required_capabilities:
                script_key = required_capabilities[0].get("script_key")
                script_running = 0
                for task in db.list_master_tasks():
                    payload = task.get("payload") or {}
                    if (
                        task.get("target_node_id") == node["node_id"]
                        and task.get("status") in {"dispatched", "running"}
                        and payload.get("script_key") == script_key
                    ):
                        script_running += 1
                if script_running >= max_running_per_script:
                    continue
            available_slots = max_profiles - effective_profiles
            candidates.append((effective_profiles, cpu, mem_ratio, node, available_slots, sorted(node_tags)))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1], item[2]))
    node = dict(candidates[0][3])
    node["available_slots"] = candidates[0][4]
    node["matched_capabilities"] = [
        {"script_key": key, "script_version": version}
        for key, version in sorted(by_node.get(node["node_id"], set()))
    ]
    node["matched_tags"] = candidates[0][5]
    return node


def _host_from_api_base(api_base: str | None) -> str | None:
    if not api_base:
        return None
    parsed = urlparse(api_base)
    return parsed.hostname or api_base


def record_worker_registration(
    node_id: str,
    capabilities: list[dict[str, Any]],
    hostname: str | None = None,
    api_base: str | None = None,
    tags: list[str] | None = None,
    max_profiles: int = 15,
) -> None:
    existing = repo.get_worker(node_id)
    host = (existing or {}).get("host") or _host_from_api_base(api_base) or hostname or node_id
    merged_tags = set((existing or {}).get("tags") or [])
    merged_tags.update(tags or [])
    repo.upsert_worker(
        {
            **(existing or {}),
            "node_id": node_id,
            "source": (existing or {}).get("source") or "registered",
            "source_record_id": (existing or {}).get("source_record_id") or node_id,
            "host": host,
            "ssh_user": (existing or {}).get("ssh_user") or "root",
            "ssh_port": (existing or {}).get("ssh_port") or 22,
            "enabled": (existing or {}).get("enabled", True),
            "desired_state": (existing or {}).get("desired_state") or "active",
            "status": "online",
            "max_profiles": max_profiles,
            "tags": sorted(merged_tags),
            "worker_api_base": api_base or (existing or {}).get("worker_api_base"),
        }
    )
    if capabilities:
        repo.replace_capabilities(node_id, capabilities)
    repo.create_event(node_id, "worker_registered", "worker registered with master", "registration")


def record_worker_heartbeat(
    node_id: str,
    status: str,
    running_profiles: int,
    cpu_percent: float | None,
    mem_total_mb: int | None,
    mem_used_mb: int | None,
    last_heartbeat_at: str | None,
    profiles: list[dict[str, Any]] | None = None,
) -> None:
    repo.record_heartbeat(node_id, status, running_profiles)
    repo.record_resource(node_id, cpu_percent, mem_total_mb, mem_used_mb, running_profiles)
    repo.replace_profiles(node_id, profiles or [])
    repo.create_event(node_id, "worker_heartbeat_received", f"running_profiles={running_profiles}", "heartbeat")
    infra_worker = repo.get_worker(node_id)
    if infra_worker:
        repo.upsert_worker(
            {
                **infra_worker,
                "status": status,
                "last_heartbeat_at": last_heartbeat_at,
            }
        )
    else:
        node = db.get_master_node(node_id) or {}
        host = _host_from_api_base(node.get("api_base")) or node.get("hostname") or node_id
        repo.upsert_worker(
            {
                "node_id": node_id,
                "source": "heartbeat",
                "source_record_id": node_id,
                "host": host,
                "ssh_user": "root",
                "ssh_port": 22,
                "enabled": True,
                "desired_state": "active",
                "status": status,
                "max_profiles": int(node.get("max_profiles") or 15),
                "tags": node.get("tags") or [],
                "worker_api_base": node.get("api_base"),
                "last_heartbeat_at": last_heartbeat_at,
            }
        )
