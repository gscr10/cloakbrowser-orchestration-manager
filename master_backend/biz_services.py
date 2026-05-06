from __future__ import annotations

from typing import Any, Protocol

from . import biz_repository as repo
from . import database as db


class WorkerSchedulerContract(Protocol):
    def __call__(
        self,
        worker_tags: list[str] | None = None,
        required_capabilities: list[dict[str, str]] | None = None,
    ) -> dict[str, Any] | None:
        ...


def build_master_task_payload(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "profile_id": job.get("profile_id"),
        "authorized_target": job.get("target_url") or job.get("script_key") or "business automation",
        "task_type": "automation_script",
        "url": job.get("target_url"),
        "timeout_seconds": 300,
        "max_retries": int(job.get("max_retries") or 1),
        "script_key": job["script_key"],
        "script_version": job["script_version"],
        "biz_job_id": job["id"],
        "biz_idempotency_key": job["idempotency_key"],
        "worker_tags": job.get("worker_tags") or [],
        "profile_name": job.get("profile_name"),
        "biz_params": job.get("params") or {},
    }


def schedule_biz_job(job_id: str, find_worker: WorkerSchedulerContract) -> dict[str, Any]:
    job = repo.get_job(job_id)
    if not job:
        raise KeyError("biz job not found")
    if not job.get("enabled"):
        raise ValueError("biz job is disabled")
    if job.get("master_task_id"):
        return job

    payload = build_master_task_payload(job)
    target = find_worker(
        worker_tags=job.get("worker_tags") or [],
        required_capabilities=[{"script_key": job["script_key"], "script_version": job["script_version"]}],
    )
    if not target:
        repo.create_event(job["id"], "job_pending_no_worker", "no available worker matched scheduling requirements")
        return repo.update_job(
            job["id"],
            status="pending_schedule",
            error_message="no available worker matched scheduling requirements",
        ) or job
    payload["target_node_id"] = target["node_id"]

    task = db.create_master_task(
        profile_id=payload.get("profile_id"),
        authorized_target=payload["authorized_target"],
        task_type="automation_script",
        payload=payload,
        timeout_seconds=int(payload["timeout_seconds"]),
        max_retries=int(payload["max_retries"]),
        target_node_id=payload.get("target_node_id"),
    )
    db.create_master_task_event(task["id"], payload.get("target_node_id"), "biz_scheduled", f"biz_job_id={job['id']}")
    repo.upsert_run(job["id"], task["id"], payload.get("target_node_id"), "assigned")
    repo.create_event(job["id"], "job_scheduled", f"master_task_id={task['id']}", payload.get("target_node_id"))
    return repo.update_job(
        job["id"],
        status="assigned" if payload.get("target_node_id") else "pending_schedule",
        assigned_worker=payload.get("target_node_id"),
        master_task_id=task["id"],
    ) or job


def mark_task_dispatched(task: dict[str, Any], node_id: str) -> None:
    payload = task.get("payload") or {}
    biz_job_id = payload.get("biz_job_id")
    if not biz_job_id:
        return
    repo.update_job(
        biz_job_id,
        status="dispatched",
        assigned_worker=node_id,
        master_task_id=task["id"],
        profile_id=task.get("profile_id") or payload.get("profile_id"),
    )
    repo.upsert_run(biz_job_id, task["id"], node_id, "dispatched")
    repo.create_event(biz_job_id, "job_dispatched", f"master_task_id={task['id']}", node_id)


def mark_task_started(task: dict[str, Any], node_id: str) -> None:
    payload = task.get("payload") or {}
    biz_job_id = payload.get("biz_job_id")
    if not biz_job_id:
        return
    repo.update_job(
        biz_job_id,
        status="running",
        assigned_worker=node_id,
        master_task_id=task["id"],
        profile_id=task.get("profile_id") or payload.get("profile_id"),
    )
    repo.upsert_run(biz_job_id, task["id"], node_id, "running")
    repo.create_event(biz_job_id, "script_started", None, node_id)


def mark_task_retrying(task: dict[str, Any], node_id: str, failure_reason: str | None) -> None:
    payload = task.get("payload") or {}
    biz_job_id = payload.get("biz_job_id")
    if not biz_job_id:
        return
    repo.update_job(biz_job_id, status="pending_schedule", error_message=failure_reason)
    repo.upsert_run(biz_job_id, task["id"], node_id, "failed", error_message=failure_reason)
    repo.create_event(biz_job_id, "job_failed_retrying", failure_reason, node_id)


def mark_task_finished(task: dict[str, Any], node_id: str, status: str, result: dict[str, Any] | None = None, failure_reason: str | None = None) -> None:
    payload = task.get("payload") or {}
    biz_job_id = payload.get("biz_job_id")
    if not biz_job_id:
        return
    if status == "success":
        import datetime as dt
        import json

        summary = json.dumps(result or {}, ensure_ascii=False) if result else "success"
        repo.update_job(
            biz_job_id,
            status="success",
            profile_id=task.get("profile_id") or payload.get("profile_id"),
            result_summary=summary,
            error_message=None,
            last_run_at=dt.datetime.now(dt.timezone.utc).isoformat(),
        )
        repo.upsert_run(biz_job_id, task["id"], node_id, "success", result=result or {})
        repo.create_event(biz_job_id, "job_success", summary, node_id)
        return
    if status == "failed":
        repo.update_job(biz_job_id, status="final_failed", error_message=failure_reason)
        repo.upsert_run(biz_job_id, task["id"], node_id, "final_failed", error_message=failure_reason)
        repo.create_event(biz_job_id, "job_failed", failure_reason, node_id)
