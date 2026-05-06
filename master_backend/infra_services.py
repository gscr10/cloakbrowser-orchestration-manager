from __future__ import annotations

import datetime as dt
from typing import Any

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
    capabilities = repo.list_capabilities()
    by_node = {}
    for cap in capabilities:
        by_node.setdefault(cap["node_id"], set()).add((cap["script_key"], cap["script_version"]))

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
        if running_profiles >= max_profiles:
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
            available_slots = max_profiles - running_profiles
            candidates.append((running_profiles, cpu, mem_ratio, node, available_slots, sorted(node_tags)))
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


def record_worker_registration(node_id: str, capabilities: list[dict[str, Any]]) -> None:
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
