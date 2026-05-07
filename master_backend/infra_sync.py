from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from . import infra_repository as repo
from . import source_registry

INFRA_WORKERS_PATH = Path(os.environ.get("MASTER_INFRA_WORKERS_PATH", "/config/infra_workers.json"))


def local_infra_workers(path: Path | None = None) -> list[dict[str, Any]]:
    source = source_registry.get_infra_source("local_json", path=path or INFRA_WORKERS_PATH)
    return source.list_workers()


def normalize_worker_record(item: dict[str, Any]) -> dict[str, Any] | None:
    node_id = str(item.get("node_id") or item.get("host") or "").strip()
    host = str(item.get("host") or "").strip()
    if not node_id or not host:
        return None
    port = int(item.get("ssh_port") or item.get("port") or 22)
    worker_api_base = item.get("worker_api_base") or f"http://{host}:8080"
    return {
        "node_id": node_id,
        "source": item.get("source") or "local_json",
        "source_record_id": item.get("source_record_id") or item.get("feishu_record_id") or node_id,
        "host": host,
        "ssh_user": item.get("ssh_user") or item.get("username") or "root",
        "ssh_password": item.get("ssh_password") or item.get("password"),
        "ssh_port": port,
        "enabled": bool(item.get("enabled", True)),
        "desired_state": item.get("desired_state") or ("active" if item.get("enabled", True) else "disabled"),
        "status": item.get("status") or "imported",
        "max_profiles": int(item.get("max_profiles") or 15),
        "region": item.get("region"),
        "tags": item.get("tags") or [],
        "worker_api_base": worker_api_base,
        "last_heartbeat_at": item.get("last_heartbeat_at"),
        "notes": item.get("notes"),
    }


def sync_infra_workers(path: Path | None = None, source_name: str = "local_json") -> dict[str, Any]:
    source = source_registry.get_infra_source(source_name, path=path or INFRA_WORKERS_PATH)
    sync_run = repo.create_sync_run(source.name, "infra_workers")
    imported = []
    try:
        for item in source.list_workers():
            normalized = normalize_worker_record(item)
            if not normalized:
                continue
            normalized["source"] = normalized.get("source") or source.name
            worker = repo.upsert_worker(normalized)
            repo.create_event(worker["node_id"], "worker_imported", f"worker imported from {source.name}", "import")
            imported.append(worker)
    except Exception as exc:
        repo.update_sync_run(sync_run["id"], status="failed", imported_count=len(imported), error_message=str(exc))
        raise
    updated_run = repo.update_sync_run(sync_run["id"], status="success", imported_count=len(imported))
    return {"source": source.name, "sync_run": updated_run, "count": len(imported), "workers": imported}
