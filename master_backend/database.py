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
            """
        )
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
