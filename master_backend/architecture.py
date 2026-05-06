from __future__ import annotations

from typing import Any

from . import database as db


def architecture_summary() -> dict[str, Any]:
    infra_workers = db.list_infra_workers()
    infra_profiles = db.list_infra_worker_profiles()
    biz_jobs = db.list_biz_jobs()
    tasks = db.list_master_tasks()
    return {
        "infra": {
            "workers": len(infra_workers),
            "online": len([w for w in infra_workers if w.get("status") == "online"]),
            "pending_deploy": len([w for w in infra_workers if w.get("desired_state") == "active" and w.get("status") in {"imported", "pending_deploy"}]),
            "running_profiles": len([p for p in infra_profiles if p.get("status") == "running"]),
        },
        "biz": {
            "jobs": len(biz_jobs),
            "pending_schedule": len([j for j in biz_jobs if j.get("status") == "pending_schedule"]),
            "assigned": len([j for j in biz_jobs if j.get("status") == "assigned"]),
        },
        "master_tasks": {
            "total": len(tasks),
            "queued": len([t for t in tasks if t.get("status") == "queued"]),
            "running": len([t for t in tasks if t.get("status") == "running"]),
        },
    }
