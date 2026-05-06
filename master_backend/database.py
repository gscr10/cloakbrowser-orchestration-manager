from __future__ import annotations

import datetime
import json
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

DATA_DIR = Path("/data")
DB_PATH = DATA_DIR / "master.db"


@contextmanager
def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
    finally:
        conn.close()


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS master_nodes (
                node_id TEXT PRIMARY KEY,
                hostname TEXT NOT NULL,
                api_base TEXT,
                token TEXT,
                tags TEXT DEFAULT '[]',
                max_profiles INTEGER NOT NULL DEFAULT 15,
                running_profiles INTEGER NOT NULL DEFAULT 0,
                cpu_percent REAL,
                mem_total_mb INTEGER,
                mem_used_mb INTEGER,
                status TEXT NOT NULL DEFAULT 'online',
                last_heartbeat_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS master_tasks (
                id TEXT PRIMARY KEY,
                profile_id TEXT,
                authorized_target TEXT NOT NULL,
                task_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                status TEXT NOT NULL,
                target_node_id TEXT,
                dispatch_id TEXT,
                failure_reason TEXT,
                retry_count INTEGER NOT NULL DEFAULT 0,
                max_retries INTEGER NOT NULL DEFAULT 1,
                timeout_seconds INTEGER NOT NULL DEFAULT 300,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS master_task_events (
                id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                node_id TEXT,
                event_type TEXT NOT NULL,
                message TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS master_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS master_provision_jobs (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                provider TEXT NOT NULL,
                total_servers INTEGER NOT NULL DEFAULT 0,
                success_count INTEGER NOT NULL DEFAULT 0,
                failed_count INTEGER NOT NULL DEFAULT 0,
                dry_run BOOLEAN NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS master_provision_job_items (
                id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL,
                node_id TEXT NOT NULL,
                host TEXT NOT NULL,
                status TEXT NOT NULL,
                message TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS infra_workers (
                node_id TEXT PRIMARY KEY,
                source TEXT NOT NULL DEFAULT 'local_json',
                source_record_id TEXT,
                host TEXT NOT NULL,
                ssh_user TEXT NOT NULL DEFAULT 'root',
                ssh_password TEXT,
                ssh_port INTEGER NOT NULL DEFAULT 22,
                enabled BOOLEAN NOT NULL DEFAULT 1,
                desired_state TEXT NOT NULL DEFAULT 'active',
                status TEXT NOT NULL DEFAULT 'imported',
                max_profiles INTEGER NOT NULL DEFAULT 15,
                region TEXT,
                tags TEXT DEFAULT '[]',
                worker_api_base TEXT,
                last_heartbeat_at TEXT,
                last_sync_at TEXT NOT NULL,
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS infra_worker_capabilities (
                node_id TEXT NOT NULL,
                script_key TEXT NOT NULL,
                script_version TEXT NOT NULL,
                input_schema_version TEXT NOT NULL DEFAULT 'v1',
                updated_at TEXT NOT NULL,
                PRIMARY KEY (node_id, script_key, script_version)
            );
            CREATE TABLE IF NOT EXISTS infra_worker_heartbeats (
                id TEXT PRIMARY KEY,
                node_id TEXT NOT NULL,
                status TEXT NOT NULL,
                running_profiles INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS infra_worker_resources (
                id TEXT PRIMARY KEY,
                node_id TEXT NOT NULL,
                cpu_percent REAL,
                mem_total_mb INTEGER,
                mem_used_mb INTEGER,
                running_profiles INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS infra_worker_profiles (
                node_id TEXT NOT NULL,
                profile_id TEXT NOT NULL,
                status TEXT NOT NULL,
                vnc_ws_port INTEGER,
                cdp_port INTEGER,
                display TEXT,
                current_url TEXT,
                title TEXT,
                last_seen_at TEXT NOT NULL,
                PRIMARY KEY (node_id, profile_id)
            );
            CREATE TABLE IF NOT EXISTS infra_sync_runs (
                id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                sync_type TEXT NOT NULL,
                status TEXT NOT NULL,
                imported_count INTEGER NOT NULL DEFAULT 0,
                error_message TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS infra_sync_errors (
                id TEXT PRIMARY KEY,
                sync_run_id TEXT,
                source_record_id TEXT,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS infra_events (
                id TEXT PRIMARY KEY,
                node_id TEXT,
                event_type TEXT NOT NULL,
                message TEXT,
                stage TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS biz_jobs (
                id TEXT PRIMARY KEY,
                job_key TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'local_json',
                source_record_id TEXT,
                run_generation INTEGER NOT NULL DEFAULT 1,
                idempotency_key TEXT NOT NULL UNIQUE,
                enabled BOOLEAN NOT NULL DEFAULT 1,
                status TEXT NOT NULL,
                script_key TEXT NOT NULL,
                script_version TEXT NOT NULL,
                account TEXT,
                target_url TEXT,
                profile_name TEXT,
                worker_tags TEXT DEFAULT '[]',
                priority INTEGER NOT NULL DEFAULT 0,
                max_retries INTEGER NOT NULL DEFAULT 1,
                params_json TEXT NOT NULL DEFAULT '{}',
                input_snapshot_json TEXT NOT NULL,
                assigned_worker TEXT,
                profile_id TEXT,
                master_task_id TEXT,
                result_summary TEXT,
                error_message TEXT,
                last_run_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS biz_job_inputs (
                id TEXT PRIMARY KEY,
                biz_job_id TEXT NOT NULL,
                input_snapshot_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS biz_job_runs (
                id TEXT PRIMARY KEY,
                biz_job_id TEXT NOT NULL,
                master_task_id TEXT,
                node_id TEXT,
                status TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                result_json TEXT NOT NULL DEFAULT '{}',
                error_message TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS biz_artifacts (
                id TEXT PRIMARY KEY,
                biz_job_id TEXT,
                run_id TEXT,
                artifact_type TEXT NOT NULL,
                uri TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS biz_events (
                id TEXT PRIMARY KEY,
                biz_job_id TEXT,
                event_type TEXT NOT NULL,
                message TEXT,
                node_id TEXT,
                created_at TEXT NOT NULL
            );
            """
        )
        cap_cols = {row[1] for row in conn.execute("PRAGMA table_info(infra_worker_capabilities)").fetchall()}
        if "input_schema_version" not in cap_cols:
            conn.execute("ALTER TABLE infra_worker_capabilities ADD COLUMN input_schema_version TEXT NOT NULL DEFAULT 'v1'")
            conn.commit()
        conn.commit()


def upsert_master_node(node_id: str, hostname: str, api_base: str | None = None, token: str | None = None, tags: list[str] | None = None, max_profiles: int = 15, running_profiles: int = 0, cpu_percent: float | None = None, mem_total_mb: int | None = None, mem_used_mb: int | None = None, status: str = "online") -> dict[str, Any]:
    now = _now()
    with get_db() as conn:
        existing = conn.execute("SELECT node_id FROM master_nodes WHERE node_id = ?", (node_id,)).fetchone()
        payload = (hostname, api_base, token, json.dumps(tags or []), max_profiles, running_profiles, cpu_percent, mem_total_mb, mem_used_mb, status, now, now, node_id)
        if existing:
            conn.execute("""UPDATE master_nodes SET hostname=?, api_base=?, token=?, tags=?, max_profiles=?, running_profiles=?, cpu_percent=?, mem_total_mb=?, mem_used_mb=?, status=?, last_heartbeat_at=?, updated_at=? WHERE node_id=?""", payload)
        else:
            conn.execute("""INSERT INTO master_nodes (hostname, api_base, token, tags, max_profiles, running_profiles, cpu_percent, mem_total_mb, mem_used_mb, status, last_heartbeat_at, created_at, updated_at, node_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", payload[:-1] + (now, node_id))
        conn.commit()
    return get_master_node(node_id)  # type: ignore[return-value]


def get_master_node(node_id: str) -> dict[str, Any] | None:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM master_nodes WHERE node_id = ?", (node_id,)).fetchone()
        if not row:
            return None
        node = dict(row)
        node["tags"] = json.loads(node.get("tags") or "[]")
        return node


def list_master_nodes() -> list[dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM master_nodes ORDER BY created_at ASC").fetchall()
        out = []
        for row in rows:
            node = dict(row)
            node["tags"] = json.loads(node.get("tags") or "[]")
            out.append(node)
        return out


def set_master_setting(key: str, value: str) -> None:
    now = _now()
    with get_db() as conn:
        conn.execute("""INSERT INTO master_settings (key, value, updated_at) VALUES (?, ?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""", (key, value, now))
        conn.commit()


def get_master_setting(key: str) -> str | None:
    with get_db() as conn:
        row = conn.execute("SELECT value FROM master_settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None


def create_master_task(authorized_target: str, task_type: str, payload: dict[str, Any], profile_id: str | None = None, timeout_seconds: int = 300, max_retries: int = 1, target_node_id: str | None = None) -> dict[str, Any]:
    now = _now()
    task_id = str(uuid.uuid4())
    with get_db() as conn:
        conn.execute("""INSERT INTO master_tasks (id, profile_id, authorized_target, task_type, payload_json, status, target_node_id, timeout_seconds, max_retries, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'queued', ?, ?, ?, ?, ?)""", (task_id, profile_id, authorized_target, task_type, json.dumps(payload), target_node_id, timeout_seconds, max_retries, now, now))
        conn.commit()
    return get_master_task(task_id)  # type: ignore[return-value]


def get_master_task(task_id: str) -> dict[str, Any] | None:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM master_tasks WHERE id = ?", (task_id,)).fetchone()
        if not row:
            return None
        task = dict(row)
        task["payload"] = json.loads(task.pop("payload_json") or "{}")
        return task


def list_master_tasks() -> list[dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM master_tasks ORDER BY created_at DESC").fetchall()
        out = []
        for row in rows:
            task = dict(row)
            task["payload"] = json.loads(task.pop("payload_json") or "{}")
            out.append(task)
        return out


def allocate_master_task(node_id: str) -> dict[str, Any] | None:
    dispatch_id = str(uuid.uuid4())
    now = _now()
    with get_db() as conn:
        row = conn.execute("SELECT id FROM master_tasks WHERE status = 'queued' AND (target_node_id = ? OR target_node_id IS NULL) ORDER BY created_at ASC LIMIT 1", (node_id,)).fetchone()
        if not row:
            return None
        updated = conn.execute("UPDATE master_tasks SET status='dispatched', dispatch_id=?, target_node_id=?, updated_at=? WHERE id=? AND status='queued'", (dispatch_id, node_id, now, row["id"]))
        if updated.rowcount == 0:
            conn.commit()
            return None
        conn.commit()
    task = get_master_task(row["id"])
    if task:
        create_master_task_event(task["id"], node_id, "dispatched", f"dispatch_id={dispatch_id}")
    return task


def update_master_task(task_id: str, **fields: Any) -> dict[str, Any] | None:
    if not fields:
        return get_master_task(task_id)
    fields["updated_at"] = _now()
    cols = [f"{k} = ?" for k in fields]
    vals = list(fields.values()) + [task_id]
    with get_db() as conn:
        conn.execute(f"UPDATE master_tasks SET {', '.join(cols)} WHERE id = ?", vals)
        conn.commit()
    return get_master_task(task_id)


def create_master_task_event(task_id: str, node_id: str | None, event_type: str, message: str | None = None) -> None:
    with get_db() as conn:
        conn.execute("INSERT INTO master_task_events (id, task_id, node_id, event_type, message, created_at) VALUES (?, ?, ?, ?, ?, ?)", (str(uuid.uuid4()), task_id, node_id, event_type, message, _now()))
        conn.commit()


def list_master_task_events(task_id: str) -> list[dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM master_task_events WHERE task_id = ? ORDER BY created_at ASC", (task_id,)).fetchall()
        return [dict(row) for row in rows]


def create_provision_job(provider: str, total_servers: int, dry_run: bool) -> dict[str, Any]:
    now = _now()
    job_id = str(uuid.uuid4())
    with get_db() as conn:
        conn.execute("INSERT INTO master_provision_jobs (id, status, provider, total_servers, dry_run, created_at, updated_at) VALUES (?, 'running', ?, ?, ?, ?, ?)", (job_id, provider, total_servers, int(dry_run), now, now))
        conn.commit()
    return get_provision_job(job_id)  # type: ignore[return-value]


def update_provision_job(job_id: str, **fields: Any) -> dict[str, Any] | None:
    if not fields:
        return get_provision_job(job_id)
    fields["updated_at"] = _now()
    cols = [f"{k} = ?" for k in fields]
    vals = list(fields.values()) + [job_id]
    with get_db() as conn:
        conn.execute(f"UPDATE master_provision_jobs SET {', '.join(cols)} WHERE id = ?", vals)
        conn.commit()
    return get_provision_job(job_id)


def get_provision_job(job_id: str) -> dict[str, Any] | None:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM master_provision_jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None


def list_provision_jobs() -> list[dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM master_provision_jobs ORDER BY created_at DESC").fetchall()
        return [dict(row) for row in rows]


def add_provision_job_item(job_id: str, node_id: str, host: str, status: str, message: str | None = None) -> dict[str, Any]:
    item_id = str(uuid.uuid4())
    now = _now()
    with get_db() as conn:
        conn.execute("INSERT INTO master_provision_job_items (id, job_id, node_id, host, status, message, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (item_id, job_id, node_id, host, status, message, now, now))
        conn.commit()
        row = conn.execute("SELECT * FROM master_provision_job_items WHERE id = ?", (item_id,)).fetchone()
        return dict(row)


def list_provision_job_items(job_id: str) -> list[dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM master_provision_job_items WHERE job_id = ? ORDER BY created_at ASC", (job_id,)).fetchall()
        return [dict(row) for row in rows]


def _json_list(value: str | None) -> list[Any]:
    try:
        parsed = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _json_dict(value: str | None) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def upsert_infra_worker(payload: dict[str, Any]) -> dict[str, Any]:
    now = _now()
    node_id = str(payload["node_id"])
    values = {
        "source": payload.get("source") or "local_json",
        "source_record_id": payload.get("source_record_id"),
        "host": payload["host"],
        "ssh_user": payload.get("ssh_user") or payload.get("username") or "root",
        "ssh_password": payload.get("ssh_password") or payload.get("password"),
        "ssh_port": int(payload.get("ssh_port") or payload.get("port") or 22),
        "enabled": int(bool(payload.get("enabled", True))),
        "desired_state": payload.get("desired_state") or "online",
        "status": payload.get("status") or "imported",
        "max_profiles": int(payload.get("max_profiles") or 15),
        "region": payload.get("region"),
        "tags": json.dumps(payload.get("tags") or []),
        "worker_api_base": payload.get("worker_api_base"),
        "last_heartbeat_at": payload.get("last_heartbeat_at"),
        "last_sync_at": now,
        "notes": payload.get("notes"),
    }
    with get_db() as conn:
        existing = conn.execute("SELECT node_id FROM infra_workers WHERE node_id = ?", (node_id,)).fetchone()
        if existing:
            conn.execute(
                """UPDATE infra_workers SET source=?, source_record_id=?, host=?, ssh_user=?,
                ssh_password=?, ssh_port=?, enabled=?, desired_state=?, status=?, max_profiles=?,
                region=?, tags=?, worker_api_base=?, last_heartbeat_at=?, last_sync_at=?,
                notes=?, updated_at=? WHERE node_id=?""",
                (
                    values["source"], values["source_record_id"], values["host"], values["ssh_user"],
                    values["ssh_password"], values["ssh_port"], values["enabled"], values["desired_state"],
                    values["status"], values["max_profiles"], values["region"], values["tags"],
                    values["worker_api_base"], values["last_heartbeat_at"], values["last_sync_at"],
                    values["notes"], now, node_id,
                ),
            )
        else:
            conn.execute(
                """INSERT INTO infra_workers (
                    node_id, source, source_record_id, host, ssh_user, ssh_password, ssh_port,
                    enabled, desired_state, status, max_profiles, region, tags, worker_api_base,
                    last_heartbeat_at, last_sync_at, notes, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    node_id, values["source"], values["source_record_id"], values["host"],
                    values["ssh_user"], values["ssh_password"], values["ssh_port"], values["enabled"],
                    values["desired_state"], values["status"], values["max_profiles"], values["region"],
                    values["tags"], values["worker_api_base"], values["last_heartbeat_at"],
                    values["last_sync_at"], values["notes"], now, now,
                ),
            )
        conn.commit()
    return get_infra_worker(node_id)  # type: ignore[return-value]


def get_infra_worker(node_id: str) -> dict[str, Any] | None:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM infra_workers WHERE node_id = ?", (node_id,)).fetchone()
        if not row:
            return None
        worker = dict(row)
        worker["tags"] = _json_list(worker.get("tags"))
        worker["enabled"] = bool(worker.get("enabled"))
        worker["capabilities"] = list_infra_worker_capabilities(node_id)
        return worker


def list_infra_workers() -> list[dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM infra_workers ORDER BY node_id ASC").fetchall()
    workers = []
    for row in rows:
        worker = get_infra_worker(dict(row)["node_id"])
        if worker:
            workers.append(worker)
    return workers


def replace_infra_worker_capabilities(node_id: str, capabilities: list[dict[str, Any]]) -> None:
    now = _now()
    with get_db() as conn:
        conn.execute("DELETE FROM infra_worker_capabilities WHERE node_id = ?", (node_id,))
        for cap in capabilities:
            script_key = str(cap.get("script_key") or cap.get("key") or "").strip()
            script_version = str(cap.get("script_version") or cap.get("version") or "").strip()
            input_schema_version = str(cap.get("input_schema_version") or "v1").strip() or "v1"
            if not script_key or not script_version:
                continue
            conn.execute(
                """INSERT OR REPLACE INTO infra_worker_capabilities
                (node_id, script_key, script_version, input_schema_version, updated_at)
                VALUES (?, ?, ?, ?, ?)""",
                (node_id, script_key, script_version, input_schema_version, now),
            )
        conn.commit()


def list_infra_worker_capabilities(node_id: str | None = None) -> list[dict[str, Any]]:
    with get_db() as conn:
        if node_id:
            rows = conn.execute("SELECT * FROM infra_worker_capabilities WHERE node_id = ? ORDER BY script_key, script_version", (node_id,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM infra_worker_capabilities ORDER BY node_id, script_key, script_version").fetchall()
        return [dict(row) for row in rows]


def record_infra_heartbeat(node_id: str, status: str, running_profiles: int) -> None:
    with get_db() as conn:
        conn.execute(
            "INSERT INTO infra_worker_heartbeats (id, node_id, status, running_profiles, created_at) VALUES (?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), node_id, status, running_profiles, _now()),
        )
        conn.commit()


def record_infra_resource(node_id: str, cpu_percent: float | None, mem_total_mb: int | None, mem_used_mb: int | None, running_profiles: int) -> None:
    with get_db() as conn:
        conn.execute(
            """INSERT INTO infra_worker_resources
            (id, node_id, cpu_percent, mem_total_mb, mem_used_mb, running_profiles, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (str(uuid.uuid4()), node_id, cpu_percent, mem_total_mb, mem_used_mb, running_profiles, _now()),
        )
        conn.commit()


def replace_infra_worker_profiles(node_id: str, profiles: list[dict[str, Any]]) -> None:
    now = _now()
    with get_db() as conn:
        conn.execute("UPDATE infra_worker_profiles SET status = 'stopped', last_seen_at = ? WHERE node_id = ?", (now, node_id))
        for item in profiles:
            profile_id = str(item.get("profile_id") or "").strip()
            if not profile_id:
                continue
            conn.execute(
                """INSERT INTO infra_worker_profiles
                (node_id, profile_id, status, vnc_ws_port, cdp_port, display, current_url, title, last_seen_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(node_id, profile_id) DO UPDATE SET
                    status=excluded.status,
                    vnc_ws_port=excluded.vnc_ws_port,
                    cdp_port=excluded.cdp_port,
                    display=excluded.display,
                    current_url=excluded.current_url,
                    title=excluded.title,
                    last_seen_at=excluded.last_seen_at""",
                (
                    node_id,
                    profile_id,
                    item.get("status") or "running",
                    item.get("vnc_ws_port"),
                    item.get("cdp_port"),
                    item.get("display"),
                    item.get("current_url"),
                    item.get("title"),
                    now,
                ),
            )
        conn.commit()


def list_infra_worker_profiles(node_id: str | None = None) -> list[dict[str, Any]]:
    with get_db() as conn:
        if node_id:
            rows = conn.execute("SELECT * FROM infra_worker_profiles WHERE node_id = ? ORDER BY last_seen_at DESC", (node_id,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM infra_worker_profiles ORDER BY last_seen_at DESC").fetchall()
        return [dict(row) for row in rows]


def create_infra_sync_run(source: str, sync_type: str, status: str = "running") -> dict[str, Any]:
    now = _now()
    run_id = str(uuid.uuid4())
    with get_db() as conn:
        conn.execute(
            "INSERT INTO infra_sync_runs (id, source, sync_type, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (run_id, source, sync_type, status, now, now),
        )
        conn.commit()
    return get_infra_sync_run(run_id)  # type: ignore[return-value]


def update_infra_sync_run(run_id: str, **fields: Any) -> dict[str, Any] | None:
    fields["updated_at"] = _now()
    cols = [f"{key} = ?" for key in fields]
    vals = list(fields.values()) + [run_id]
    with get_db() as conn:
        conn.execute(f"UPDATE infra_sync_runs SET {', '.join(cols)} WHERE id = ?", vals)
        conn.commit()
    return get_infra_sync_run(run_id)


def get_infra_sync_run(run_id: str) -> dict[str, Any] | None:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM infra_sync_runs WHERE id = ?", (run_id,)).fetchone()
        return dict(row) if row else None


def list_infra_sync_runs() -> list[dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM infra_sync_runs ORDER BY created_at DESC").fetchall()
        return [dict(row) for row in rows]


def create_infra_event(node_id: str | None, event_type: str, message: str | None = None, stage: str | None = None) -> None:
    with get_db() as conn:
        conn.execute(
            "INSERT INTO infra_events (id, node_id, event_type, message, stage, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), node_id, event_type, message, stage, _now()),
        )
        conn.commit()


def list_infra_events(limit: int = 100) -> list[dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM infra_events ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]


def upsert_biz_job(payload: dict[str, Any]) -> dict[str, Any]:
    now = _now()
    source = payload.get("source") or "local_json"
    source_record_id = str(payload.get("source_record_id") or payload.get("feishu_record_id") or payload.get("job_key"))
    run_generation = int(payload.get("run_generation") or 1)
    idempotency_key = payload.get("idempotency_key") or f"{source_record_id}:{run_generation}"
    job_id = str(payload.get("id") or uuid.uuid5(uuid.NAMESPACE_URL, f"cloak-biz:{idempotency_key}"))
    params = payload.get("params") or payload.get("params_json") or {}
    if isinstance(params, str):
        params = _json_dict(params)
    snapshot = dict(payload)
    values = {
        "job_key": payload.get("job_key") or source_record_id,
        "source": source,
        "source_record_id": source_record_id,
        "run_generation": run_generation,
        "idempotency_key": idempotency_key,
        "enabled": int(bool(payload.get("enabled", True))),
        "status": payload.get("status") or "imported",
        "script_key": payload["script_key"],
        "script_version": payload.get("script_version") or "v1",
        "account": payload.get("account"),
        "target_url": payload.get("target_url"),
        "profile_name": payload.get("profile_name"),
        "worker_tags": json.dumps(payload.get("worker_tags") or []),
        "priority": int(payload.get("priority") or 0),
        "max_retries": int(payload.get("max_retries") or 1),
        "params_json": json.dumps(params),
        "input_snapshot_json": json.dumps(snapshot),
        "assigned_worker": payload.get("assigned_worker"),
        "profile_id": payload.get("profile_id"),
        "master_task_id": payload.get("master_task_id"),
        "result_summary": payload.get("result_summary"),
        "error_message": payload.get("error_message"),
        "last_run_at": payload.get("last_run_at"),
    }
    with get_db() as conn:
        existing = conn.execute("SELECT id FROM biz_jobs WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
        if existing:
            job_id = existing["id"]
            conn.execute(
                """UPDATE biz_jobs SET job_key=?, source=?, source_record_id=?, run_generation=?,
                enabled=?, status=?, script_key=?, script_version=?, account=?, target_url=?,
                profile_name=?, worker_tags=?, priority=?, max_retries=?, params_json=?,
                input_snapshot_json=?, assigned_worker=?, profile_id=?, master_task_id=?,
                result_summary=?, error_message=?, last_run_at=?, updated_at=? WHERE id=?""",
                (
                    values["job_key"], values["source"], values["source_record_id"], values["run_generation"],
                    values["enabled"], values["status"], values["script_key"], values["script_version"],
                    values["account"], values["target_url"], values["profile_name"], values["worker_tags"],
                    values["priority"], values["max_retries"], values["params_json"], values["input_snapshot_json"],
                    values["assigned_worker"], values["profile_id"], values["master_task_id"],
                    values["result_summary"], values["error_message"], values["last_run_at"], now, job_id,
                ),
            )
        else:
            conn.execute(
                """INSERT INTO biz_jobs (
                    id, job_key, source, source_record_id, run_generation, idempotency_key,
                    enabled, status, script_key, script_version, account, target_url, profile_name,
                    worker_tags, priority, max_retries, params_json, input_snapshot_json,
                    assigned_worker, profile_id, master_task_id, result_summary, error_message,
                    last_run_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    job_id, values["job_key"], values["source"], values["source_record_id"],
                    values["run_generation"], values["idempotency_key"], values["enabled"], values["status"],
                    values["script_key"], values["script_version"], values["account"], values["target_url"],
                    values["profile_name"], values["worker_tags"], values["priority"], values["max_retries"],
                    values["params_json"], values["input_snapshot_json"], values["assigned_worker"],
                    values["profile_id"], values["master_task_id"], values["result_summary"],
                    values["error_message"], values["last_run_at"], now, now,
                ),
            )
            conn.execute(
                "INSERT INTO biz_job_inputs (id, biz_job_id, input_snapshot_json, created_at) VALUES (?, ?, ?, ?)",
                (str(uuid.uuid4()), job_id, values["input_snapshot_json"], now),
            )
        conn.commit()
    return get_biz_job(job_id)  # type: ignore[return-value]


def get_biz_job(job_id: str) -> dict[str, Any] | None:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM biz_jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            return None
        job = dict(row)
        job["enabled"] = bool(job.get("enabled"))
        job["worker_tags"] = _json_list(job.get("worker_tags"))
        job["params"] = _json_dict(job.pop("params_json", None))
        job["input_snapshot"] = _json_dict(job.pop("input_snapshot_json", None))
        return job


def list_biz_jobs() -> list[dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute("SELECT id FROM biz_jobs ORDER BY priority DESC, created_at ASC").fetchall()
    return [job for row in rows if (job := get_biz_job(row["id"]))]


def update_biz_job(job_id: str, **fields: Any) -> dict[str, Any] | None:
    if not fields:
        return get_biz_job(job_id)
    if "worker_tags" in fields:
        fields["worker_tags"] = json.dumps(fields["worker_tags"] or [])
    if "params" in fields:
        fields["params_json"] = json.dumps(fields.pop("params") or {})
    fields["updated_at"] = _now()
    cols = [f"{key} = ?" for key in fields]
    vals = list(fields.values()) + [job_id]
    with get_db() as conn:
        conn.execute(f"UPDATE biz_jobs SET {', '.join(cols)} WHERE id = ?", vals)
        conn.commit()
    return get_biz_job(job_id)


def upsert_biz_job_run(biz_job_id: str, master_task_id: str | None, node_id: str | None, status: str, result: dict[str, Any] | None = None, error_message: str | None = None) -> dict[str, Any]:
    now = _now()
    result_json = json.dumps(result or {})
    with get_db() as conn:
        existing = None
        if master_task_id:
            existing = conn.execute("SELECT id FROM biz_job_runs WHERE master_task_id = ?", (master_task_id,)).fetchone()
        if existing:
            fields = {
                "node_id": node_id,
                "status": status,
                "result_json": result_json,
                "error_message": error_message,
                "updated_at": now,
            }
            if status in {"running", "dispatched"}:
                fields["started_at"] = now
            if status in {"success", "failed", "final_failed"}:
                fields["finished_at"] = now
            cols = [f"{key} = ?" for key in fields]
            conn.execute(f"UPDATE biz_job_runs SET {', '.join(cols)} WHERE id = ?", list(fields.values()) + [existing["id"]])
            run_id = existing["id"]
        else:
            run_id = str(uuid.uuid4())
            started_at = now if status in {"running", "dispatched"} else None
            finished_at = now if status in {"success", "failed", "final_failed"} else None
            conn.execute(
                """INSERT INTO biz_job_runs
                (id, biz_job_id, master_task_id, node_id, status, started_at, finished_at,
                 result_json, error_message, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (run_id, biz_job_id, master_task_id, node_id, status, started_at, finished_at, result_json, error_message, now, now),
            )
        conn.commit()
    return get_biz_job_run(run_id)  # type: ignore[return-value]


def get_biz_job_run(run_id: str) -> dict[str, Any] | None:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM biz_job_runs WHERE id = ?", (run_id,)).fetchone()
        if not row:
            return None
        run = dict(row)
        run["result"] = _json_dict(run.pop("result_json", None))
        return run


def list_biz_job_runs(biz_job_id: str | None = None) -> list[dict[str, Any]]:
    with get_db() as conn:
        if biz_job_id:
            rows = conn.execute("SELECT id FROM biz_job_runs WHERE biz_job_id = ? ORDER BY created_at DESC", (biz_job_id,)).fetchall()
        else:
            rows = conn.execute("SELECT id FROM biz_job_runs ORDER BY created_at DESC").fetchall()
    return [run for row in rows if (run := get_biz_job_run(row["id"]))]


def create_biz_artifact(biz_job_id: str | None, run_id: str | None, artifact_type: str, uri: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    artifact_id = str(uuid.uuid4())
    with get_db() as conn:
        conn.execute(
            """INSERT INTO biz_artifacts
            (id, biz_job_id, run_id, artifact_type, uri, metadata_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (artifact_id, biz_job_id, run_id, artifact_type, uri, json.dumps(metadata or {}), _now()),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM biz_artifacts WHERE id = ?", (artifact_id,)).fetchone()
        artifact = dict(row)
        artifact["metadata"] = _json_dict(artifact.pop("metadata_json", None))
        return artifact


def list_biz_artifacts(biz_job_id: str | None = None) -> list[dict[str, Any]]:
    with get_db() as conn:
        if biz_job_id:
            rows = conn.execute("SELECT * FROM biz_artifacts WHERE biz_job_id = ? ORDER BY created_at DESC", (biz_job_id,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM biz_artifacts ORDER BY created_at DESC").fetchall()
        out = []
        for row in rows:
            artifact = dict(row)
            artifact["metadata"] = _json_dict(artifact.pop("metadata_json", None))
            out.append(artifact)
        return out


def create_biz_event(biz_job_id: str | None, event_type: str, message: str | None = None, node_id: str | None = None) -> None:
    with get_db() as conn:
        conn.execute(
            "INSERT INTO biz_events (id, biz_job_id, event_type, message, node_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), biz_job_id, event_type, message, node_id, _now()),
        )
        conn.commit()


def list_biz_events(limit: int = 100) -> list[dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM biz_events ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]
