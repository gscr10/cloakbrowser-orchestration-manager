from __future__ import annotations

import datetime as dt
import json
from typing import Any, Protocol

from . import biz_repository as repo
from . import biz_validation
from . import database as db
from . import writeback


class WorkerSchedulerContract(Protocol):
    def __call__(
        self,
        worker_tags: list[str] | None = None,
        required_capabilities: list[dict[str, str]] | None = None,
    ) -> dict[str, Any] | None:
        ...


def _int_with_default(value: Any, default: int) -> int:
    return default if value is None else int(value)


def build_master_task_payload(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "profile_id": job.get("profile_id"),
        "authorized_target": job.get("target_url") or job.get("script_key") or "business automation",
        "task_type": "automation_script",
        "url": job.get("target_url"),
        "timeout_seconds": 300,
        "max_retries": _int_with_default(job.get("max_retries"), 1),
        "script_key": job["script_key"],
        "script_version": job["script_version"],
        "account": job.get("account"),
        "biz_job_id": job["id"],
        "biz_idempotency_key": job["idempotency_key"],
        "worker_tags": job.get("worker_tags") or [],
        "profile_name": job.get("profile_name"),
        "priority": int(job.get("priority") or 0),
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
    valid, error_message = biz_validation.validate_job_payload(job)
    if not valid:
        repo.create_event(job["id"], "job_input_invalid", error_message)
        return repo.update_job(job["id"], status="invalid", error_message=error_message) or job

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
        priority=int(payload.get("priority") or 0),
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


def _result_artifacts(result: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not result:
        return []
    candidates: list[Any] = []
    if isinstance(result.get("artifacts"), list):
        candidates.extend(result["artifacts"])
    nested = result.get("result")
    if isinstance(nested, dict) and isinstance(nested.get("artifacts"), list):
        candidates.extend(nested["artifacts"])
    return [item for item in candidates if isinstance(item, dict)]


def _persist_artifacts(biz_job_id: str, run_id: str | None, result: dict[str, Any] | None) -> None:
    for item in _result_artifacts(result):
        uri = item.get("uri") or item.get("url") or item.get("path")
        if not uri:
            continue
        artifact_type = item.get("artifact_type") or item.get("type") or "file"
        metadata = {key: value for key, value in item.items() if key not in {"uri", "url", "path", "artifact_type", "type"}}
        repo.create_artifact(biz_job_id, run_id, str(artifact_type), str(uri), metadata)


def _record_writeback(biz_job_id: str, status: str, payload: dict[str, Any], node_id: str) -> None:
    job = repo.get_job(biz_job_id)
    if not job:
        return
    result = writeback.write_biz_status(job, status, payload)
    event_type = "biz_writeback_success" if result.get("written") else "biz_writeback_skipped"
    repo.create_event(biz_job_id, event_type, str(result), node_id)


def mark_task_finished(task: dict[str, Any], node_id: str, status: str, result: dict[str, Any] | None = None, failure_reason: str | None = None) -> None:
    payload = task.get("payload") or {}
    biz_job_id = payload.get("biz_job_id")
    if not biz_job_id:
        return
    if status == "success":
        summary = json.dumps(result or {}, ensure_ascii=False) if result else "success"
        repo.update_job(
            biz_job_id,
            status="success",
            profile_id=task.get("profile_id") or payload.get("profile_id"),
            result_summary=summary,
            error_message=None,
            last_run_at=dt.datetime.now(dt.timezone.utc).isoformat(),
        )
        run = repo.upsert_run(biz_job_id, task["id"], node_id, "success", result=result or {})
        _persist_artifacts(biz_job_id, run.get("id"), result or {})
        _record_writeback(biz_job_id, "success", {"result_summary": summary, "result": result or {}}, node_id)
        repo.create_event(biz_job_id, "job_success", summary, node_id)
        return
    if status == "failed":
        repo.update_job(
            biz_job_id,
            status="final_failed",
            error_message=failure_reason,
            last_run_at=dt.datetime.now(dt.timezone.utc).isoformat(),
        )
        run = repo.upsert_run(biz_job_id, task["id"], node_id, "final_failed", result=result or {}, error_message=failure_reason)
        _persist_artifacts(biz_job_id, run.get("id"), result or {})
        _record_writeback(biz_job_id, "final_failed", {"error_message": failure_reason, "result": result or {}}, node_id)
        repo.create_event(biz_job_id, "job_failed", failure_reason, node_id)
        return
    if status == "cancelled":
        repo.update_job(
            biz_job_id,
            status="cancelled",
            error_message=failure_reason,
            last_run_at=dt.datetime.now(dt.timezone.utc).isoformat(),
        )
        repo.upsert_run(biz_job_id, task["id"], node_id, "cancelled", result=result or {}, error_message=failure_reason)
        _record_writeback(biz_job_id, "cancelled", {"error_message": failure_reason, "result": result or {}}, node_id)
        repo.create_event(biz_job_id, "job_cancelled", failure_reason, node_id)


def cancel_biz_job(job_id: str, reason: str | None = None) -> dict[str, Any]:
    job = repo.get_job(job_id)
    if not job:
        raise KeyError("biz job not found")
    repo.create_event(job_id, "job_cancelled", reason or "cancelled by operator", job.get("assigned_worker"))
    return repo.update_job(job_id, status="cancelled", error_message=reason) or job


def requeue_biz_job(job_id: str) -> dict[str, Any]:
    job = repo.get_job(job_id)
    if not job:
        raise KeyError("biz job not found")
    updates: dict[str, Any] = {
        "status": "pending_schedule",
        "assigned_worker": None,
        "profile_id": None,
        "master_task_id": None,
        "result_summary": None,
        "error_message": None,
    }
    repo.create_event(job_id, "job_requeued", "operator requested requeue", job.get("assigned_worker"))
    return repo.update_job(job_id, **updates) or job


def recover_stuck_master_tasks(older_than_seconds: int = 600) -> dict[str, Any]:
    now = dt.datetime.now(dt.timezone.utc)
    recovered: list[dict[str, Any]] = []
    for task in db.list_master_tasks():
        if task.get("status") not in {"dispatched", "running"}:
            continue
        updated_at_raw = task.get("updated_at") or task.get("created_at")
        try:
            updated_at = dt.datetime.fromisoformat(updated_at_raw)
        except (TypeError, ValueError):
            updated_at = now
        age = (now - updated_at).total_seconds()
        threshold = max(older_than_seconds, int(task.get("timeout_seconds") or 0))
        if age < threshold:
            continue
        retry_count = int(task.get("retry_count") or 0)
        max_retries = int(task.get("max_retries") or 0)
        if retry_count < max_retries:
            updated = db.update_master_task(
                task["id"],
                status="queued",
                retry_count=retry_count + 1,
                dispatch_id=None,
                failure_reason="recovered stuck task",
            )
            db.create_master_task_event(task["id"], task.get("target_node_id"), "stuck_requeued", "recovered stuck task")
        else:
            updated = db.update_master_task(
                task["id"],
                status="failed",
                failure_reason="stuck task exceeded recovery threshold",
            )
            db.create_master_task_event(task["id"], task.get("target_node_id"), "stuck_failed", "stuck task exceeded recovery threshold")
            mark_task_finished(task, task.get("target_node_id") or "", "failed", result={}, failure_reason="stuck task exceeded recovery threshold")
        if updated:
            recovered.append(updated)
    return {"count": len(recovered), "tasks": recovered}
