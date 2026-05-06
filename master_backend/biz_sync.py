from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from . import biz_repository as repo
from .json_sources import load_items

BIZ_TASKS_PATH = Path(os.environ.get("MASTER_BIZ_TASKS_PATH", "/config/biz_tasks.json"))


def local_biz_tasks(path: Path | None = None) -> list[dict[str, Any]]:
    return load_items(path or BIZ_TASKS_PATH, "jobs")


def normalize_biz_job(item: dict[str, Any]) -> dict[str, Any] | None:
    script_key = str(item.get("script_key") or "").strip()
    if not script_key:
        return None
    job_key = str(item.get("job_key") or item.get("source_record_id") or item.get("feishu_record_id") or "").strip()
    if not job_key:
        job_key = script_key
    run_generation = int(item.get("run_generation") or 1)
    source_record_id = str(item.get("source_record_id") or item.get("feishu_record_id") or job_key)
    status = item.get("status") or "imported"
    if status == "pending":
        status = "pending_schedule"
    return {
        "job_key": job_key,
        "source": item.get("source") or "local_json",
        "source_record_id": source_record_id,
        "run_generation": run_generation,
        "idempotency_key": item.get("idempotency_key") or f"{source_record_id}:{run_generation}",
        "enabled": bool(item.get("enabled", True)),
        "status": status,
        "script_key": script_key,
        "script_version": item.get("script_version") or "v1",
        "account": item.get("account"),
        "target_url": item.get("target_url"),
        "profile_name": item.get("profile_name"),
        "worker_tags": item.get("worker_tags") or [],
        "priority": int(item.get("priority") or 0),
        "max_retries": int(item.get("max_retries") or 1),
        "params": item.get("params_json") or item.get("params") or {},
        "assigned_worker": item.get("assigned_worker"),
        "profile_id": item.get("profile_id"),
    }


def sync_biz_jobs(path: Path | None = None) -> dict[str, Any]:
    imported = []
    for item in local_biz_tasks(path):
        normalized = normalize_biz_job(item)
        if not normalized:
            continue
        job = repo.upsert_job(normalized)
        repo.create_event(job["id"], "job_imported", "business job imported from local_json")
        imported.append(job)
    return {"source": "local_json", "count": len(imported), "jobs": imported}
