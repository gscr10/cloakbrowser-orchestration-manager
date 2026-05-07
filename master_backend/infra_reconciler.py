from __future__ import annotations

import datetime as dt
from typing import Any

from . import database as db
from . import infra_repository as repo
from . import master_control


def _parse_ts(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value)
    except ValueError:
        return None


def _node_status(node_id: str, heartbeat_ttl_seconds: int) -> tuple[str, dict[str, Any] | None]:
    node = db.get_master_node(node_id)
    if not node:
        return "missing", None
    status = node.get("status") or "unknown"
    hb = _parse_ts(node.get("last_heartbeat_at"))
    if status == "online" and hb:
        age = (dt.datetime.now(dt.timezone.utc) - hb).total_seconds()
        if age > heartbeat_ttl_seconds:
            return "stale", node
    return status, node


def plan_reconcile(heartbeat_ttl_seconds: int | None = None) -> dict[str, Any]:
    ttl = heartbeat_ttl_seconds or master_control.NODE_HEARTBEAT_TTL_SECONDS
    items: list[dict[str, Any]] = []
    for worker in repo.list_workers():
        desired = worker.get("desired_state") or ("active" if worker.get("enabled", True) else "disabled")
        actual, node = _node_status(worker["node_id"], ttl)
        action = "observe"
        reason = "worker is within desired state"
        if desired == "active" and actual in {"missing", "offline", "stale"}:
            action = "deploy"
            reason = f"desired active but node is {actual}"
        elif desired == "active" and worker.get("status") in {"imported", "pending_deploy", "deploy_failed"}:
            action = "deploy"
            reason = f"desired active but infra status is {worker.get('status')}"
        elif desired in {"disabled", "inactive"}:
            action = "disable"
            reason = "desired state disables scheduling and marks the worker out of service"
        elif desired in {"restart", "redeploy"}:
            action = "redeploy"
            reason = "desired state requests a restart/redeploy"
        elif desired in {"absent", "cleanup"}:
            action = "cleanup"
            reason = "desired state requests local inventory cleanup"
        items.append(
            {
                "node_id": worker["node_id"],
                "desired_state": desired,
                "actual_status": actual,
                "infra_status": worker.get("status"),
                "action": action,
                "reason": reason,
                "host": worker.get("host"),
                "running_profiles": (node or {}).get("running_profiles", 0),
            }
        )
    return {
        "mode": "plan",
        "count": len(items),
        "actions": items,
        "action_counts": {name: len([item for item in items if item["action"] == name]) for name in sorted({item["action"] for item in items})},
    }


def apply_reconcile(dry_run: bool = True, node_id: str | None = None) -> dict[str, Any]:
    plan = plan_reconcile()
    candidates = [item for item in plan["actions"] if not node_id or item["node_id"] == node_id]
    applied: list[dict[str, Any]] = []
    for item in candidates:
        action = item["action"]
        if dry_run or action == "observe":
            applied.append({**item, "applied": False})
            continue
        if action in {"deploy", "redeploy"}:
            result = master_control.run_provision(dry_run=False, node_id=item["node_id"])
            repo.create_event(item["node_id"], "reconcile_deploy_requested", item["reason"], "reconcile")
            applied.append({**item, "applied": True, "result": result.get("job")})
            continue
        if action == "disable":
            worker = repo.get_worker(item["node_id"])
            if worker:
                repo.upsert_worker({**worker, "enabled": False, "desired_state": "disabled", "status": "disabled"})
            repo.create_event(item["node_id"], "reconcile_worker_disabled", item["reason"], "reconcile")
            applied.append({**item, "applied": True})
            continue
        if action == "cleanup":
            repo.create_event(item["node_id"], "reconcile_cleanup_planned", "manual cleanup required for safety", "reconcile")
            applied.append({**item, "applied": False, "reason": "manual cleanup required for safety"})
            continue
        applied.append({**item, "applied": False})
    return {"dry_run": dry_run, "count": len(applied), "actions": applied}
