from __future__ import annotations

from typing import Any

from . import database as db


def upsert_job(payload: dict[str, Any]) -> dict[str, Any]:
    return db.upsert_biz_job(payload)


def get_job(job_id: str) -> dict[str, Any] | None:
    return db.get_biz_job(job_id)


def list_jobs() -> list[dict[str, Any]]:
    return db.list_biz_jobs()


def update_job(job_id: str, **fields: Any) -> dict[str, Any] | None:
    return db.update_biz_job(job_id, **fields)


def upsert_run(
    biz_job_id: str,
    master_task_id: str | None,
    node_id: str | None,
    status: str,
    result: dict[str, Any] | None = None,
    error_message: str | None = None,
) -> dict[str, Any]:
    return db.upsert_biz_job_run(biz_job_id, master_task_id, node_id, status, result, error_message)


def list_runs(biz_job_id: str | None = None) -> list[dict[str, Any]]:
    return db.list_biz_job_runs(biz_job_id)


def create_artifact(
    biz_job_id: str | None,
    run_id: str | None,
    artifact_type: str,
    uri: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return db.create_biz_artifact(biz_job_id, run_id, artifact_type, uri, metadata)


def list_artifacts(biz_job_id: str | None = None) -> list[dict[str, Any]]:
    return db.list_biz_artifacts(biz_job_id)


def get_artifact(artifact_id: str) -> dict[str, Any] | None:
    return db.get_biz_artifact(artifact_id)


def create_event(biz_job_id: str | None, event_type: str, message: str | None = None, node_id: str | None = None) -> None:
    db.create_biz_event(biz_job_id, event_type, message, node_id)


def list_events(limit: int = 100) -> list[dict[str, Any]]:
    return db.list_biz_events(limit)
