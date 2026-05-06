from __future__ import annotations

from typing import Any

from . import database as db


def upsert_worker(payload: dict[str, Any]) -> dict[str, Any]:
    return db.upsert_infra_worker(payload)


def get_worker(node_id: str) -> dict[str, Any] | None:
    return db.get_infra_worker(node_id)


def list_workers() -> list[dict[str, Any]]:
    return db.list_infra_workers()


def replace_capabilities(node_id: str, capabilities: list[dict[str, Any]]) -> None:
    db.replace_infra_worker_capabilities(node_id, capabilities)


def list_capabilities(node_id: str | None = None) -> list[dict[str, Any]]:
    return db.list_infra_worker_capabilities(node_id)


def record_heartbeat(node_id: str, status: str, running_profiles: int) -> None:
    db.record_infra_heartbeat(node_id, status, running_profiles)


def record_resource(
    node_id: str,
    cpu_percent: float | None,
    mem_total_mb: int | None,
    mem_used_mb: int | None,
    running_profiles: int,
) -> None:
    db.record_infra_resource(node_id, cpu_percent, mem_total_mb, mem_used_mb, running_profiles)


def replace_profiles(node_id: str, profiles: list[dict[str, Any]]) -> None:
    db.replace_infra_worker_profiles(node_id, profiles)


def list_profiles(node_id: str | None = None) -> list[dict[str, Any]]:
    return db.list_infra_worker_profiles(node_id)


def create_sync_run(source: str, sync_type: str, status: str = "running") -> dict[str, Any]:
    return db.create_infra_sync_run(source, sync_type, status)


def update_sync_run(run_id: str, **fields: Any) -> dict[str, Any] | None:
    return db.update_infra_sync_run(run_id, **fields)


def list_sync_runs() -> list[dict[str, Any]]:
    return db.list_infra_sync_runs()


def create_event(node_id: str | None, event_type: str, message: str | None = None, stage: str | None = None) -> None:
    db.create_infra_event(node_id, event_type, message, stage)


def list_events(limit: int = 100) -> list[dict[str, Any]]:
    return db.list_infra_events(limit)
