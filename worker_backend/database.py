"""SQLite database operations for browser profiles."""

from __future__ import annotations

import datetime
import csv
import io
import json
import random
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

DATA_DIR = Path("/data")
DB_PATH = DATA_DIR / "profiles.db"


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


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS profiles (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                fingerprint_seed INTEGER NOT NULL,
                proxy TEXT,
                timezone TEXT,
                locale TEXT,
                platform TEXT DEFAULT 'windows',
                user_agent TEXT,
                screen_width INTEGER DEFAULT 1920,
                screen_height INTEGER DEFAULT 1080,
                gpu_vendor TEXT,
                gpu_renderer TEXT,
                hardware_concurrency INTEGER,
                humanize BOOLEAN DEFAULT 0,
                human_preset TEXT DEFAULT 'default',
                human_config TEXT DEFAULT '{}',
                headless BOOLEAN DEFAULT 0,
                geoip BOOLEAN DEFAULT 0,
                backend TEXT,
                stealth_args BOOLEAN DEFAULT 1,
                minimal_cloak BOOLEAN DEFAULT 0,
                clipboard_sync BOOLEAN DEFAULT 1,
                color_scheme TEXT,
                notes TEXT,
                user_data_dir TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS profile_tags (
                profile_id TEXT REFERENCES profiles(id) ON DELETE CASCADE,
                tag TEXT NOT NULL,
                color TEXT,
                PRIMARY KEY (profile_id, tag)
            );

            CREATE TABLE IF NOT EXISTS proxy_endpoints (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                protocol TEXT NOT NULL,
                host TEXT NOT NULL,
                port INTEGER NOT NULL,
                username TEXT,
                password TEXT,
                region TEXT,
                tags TEXT DEFAULT '[]',
                health TEXT DEFAULT 'unknown',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(protocol, host, port, username)
            );

            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                profile_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
                authorized_target TEXT NOT NULL,
                task_type TEXT NOT NULL,
                url TEXT,
                payload_json TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL,
                proxy_id TEXT REFERENCES proxy_endpoints(id),
                run_id TEXT,
                failure_reason TEXT,
                timeout_seconds INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS profile_runs (
                id TEXT PRIMARY KEY,
                profile_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
                task_id TEXT REFERENCES tasks(id),
                proxy_id TEXT REFERENCES proxy_endpoints(id),
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                stopped_at TEXT,
                failure_reason TEXT
            );

        """)
        conn.commit()

        # Migrations for existing databases
        cols = {row[1] for row in conn.execute("PRAGMA table_info(profiles)").fetchall()}
        if "clipboard_sync" not in cols:
            conn.execute("ALTER TABLE profiles ADD COLUMN clipboard_sync BOOLEAN DEFAULT 1")
            conn.commit()
        if "launch_args" not in cols:
            conn.execute("ALTER TABLE profiles ADD COLUMN launch_args TEXT DEFAULT '[]'")
            conn.commit()
        if "human_config" not in cols:
            conn.execute("ALTER TABLE profiles ADD COLUMN human_config TEXT DEFAULT '{}'")
            conn.commit()
        if "backend" not in cols:
            conn.execute("ALTER TABLE profiles ADD COLUMN backend TEXT")
            conn.commit()
        if "stealth_args" not in cols:
            conn.execute("ALTER TABLE profiles ADD COLUMN stealth_args BOOLEAN DEFAULT 1")
            conn.commit()
        if "minimal_cloak" not in cols:
            conn.execute("ALTER TABLE profiles ADD COLUMN minimal_cloak BOOLEAN DEFAULT 0")
            conn.commit()
        task_cols = {row[1] for row in conn.execute("PRAGMA table_info(tasks)").fetchall()}
        if "payload_json" not in task_cols:
            conn.execute("ALTER TABLE tasks ADD COLUMN payload_json TEXT NOT NULL DEFAULT '{}'")
            conn.commit()


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def create_profile(
    name: str,
    fingerprint_seed: int | None = None,
    **fields: Any,
) -> dict[str, Any]:
    profile_id = str(uuid.uuid4())
    seed = fingerprint_seed if fingerprint_seed is not None else random.randint(10000, 99999)
    user_data_dir = str(DATA_DIR / "profiles" / profile_id)
    now = _now()
    tags = fields.pop("tags", None) or []

    with get_db() as conn:
        conn.execute(
            """INSERT INTO profiles (
                id, name, fingerprint_seed, proxy, timezone, locale, platform,
                user_agent, screen_width, screen_height, gpu_vendor, gpu_renderer,
                hardware_concurrency, humanize, human_preset, human_config, headless,
                geoip, backend, stealth_args, minimal_cloak, clipboard_sync, color_scheme,
                launch_args, notes, user_data_dir, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                profile_id, name, seed,
                fields.get("proxy"),
                fields.get("timezone"),
                fields.get("locale"),
                fields.get("platform", "windows"),
                fields.get("user_agent"),
                fields.get("screen_width", 1920),
                fields.get("screen_height", 1080),
                fields.get("gpu_vendor"),
                fields.get("gpu_renderer"),
                fields.get("hardware_concurrency"),
                fields.get("humanize", False),
                fields.get("human_preset", "default"),
                json.dumps(fields.get("human_config") or {}),
                fields.get("headless", False),
                fields.get("geoip", False),
                fields.get("backend"),
                fields.get("stealth_args", True),
                fields.get("minimal_cloak", False),
                fields.get("clipboard_sync", True),
                fields.get("color_scheme"),
                json.dumps(fields.get("launch_args") or []),
                fields.get("notes"),
                user_data_dir, now, now,
            ),
        )
        for t in tags:
            conn.execute(
                "INSERT INTO profile_tags (profile_id, tag, color) VALUES (?, ?, ?)",
                (profile_id, t["tag"], t.get("color")),
            )
        conn.commit()

    return get_profile(profile_id)  # type: ignore[return-value]


def get_profile(profile_id: str) -> dict[str, Any] | None:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,)).fetchone()
        if not row:
            return None
        profile = dict(row)
        profile["launch_args"] = json.loads(profile.get("launch_args") or "[]")
        profile["human_config"] = json.loads(profile.get("human_config") or "{}")
        tags = conn.execute(
            "SELECT tag, color FROM profile_tags WHERE profile_id = ?",
            (profile_id,),
        ).fetchall()
        profile["tags"] = [dict(t) for t in tags]
        return profile


def list_profiles() -> list[dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM profiles ORDER BY created_at DESC").fetchall()
        profiles = []
        for row in rows:
            profile = dict(row)
            profile["launch_args"] = json.loads(profile.get("launch_args") or "[]")
            profile["human_config"] = json.loads(profile.get("human_config") or "{}")
            tags = conn.execute(
                "SELECT tag, color FROM profile_tags WHERE profile_id = ?",
                (profile["id"],),
            ).fetchall()
            profile["tags"] = [dict(t) for t in tags]
            profiles.append(profile)
        return profiles


def update_profile(profile_id: str, **fields: Any) -> dict[str, Any] | None:
    existing = get_profile(profile_id)
    if not existing:
        return None

    tags = fields.pop("tags", None)

    # Only update fields that were explicitly provided
    update_cols = []
    update_vals = []
    # Pre-serialize launch_args to JSON before the generic update loop
    if "launch_args" in fields:
        fields["launch_args"] = json.dumps(fields["launch_args"] or [])
    if "human_config" in fields:
        fields["human_config"] = json.dumps(fields["human_config"] or {})

    for col in (
        "name", "fingerprint_seed", "proxy", "timezone", "locale", "platform",
        "user_agent", "screen_width", "screen_height", "gpu_vendor", "gpu_renderer",
        "hardware_concurrency", "humanize", "human_preset", "human_config", "headless",
        "geoip", "backend", "stealth_args", "minimal_cloak", "clipboard_sync",
        "color_scheme", "launch_args", "notes",
    ):
        if col in fields:
            update_cols.append(f"{col} = ?")
            update_vals.append(fields[col])

    if update_cols:
        update_cols.append("updated_at = ?")
        update_vals.append(_now())
        update_vals.append(profile_id)
        with get_db() as conn:
            conn.execute(
                f"UPDATE profiles SET {', '.join(update_cols)} WHERE id = ?",
                update_vals,
            )
            conn.commit()

    if tags is not None:
        with get_db() as conn:
            conn.execute("DELETE FROM profile_tags WHERE profile_id = ?", (profile_id,))
            for t in tags:
                conn.execute(
                    "INSERT INTO profile_tags (profile_id, tag, color) VALUES (?, ?, ?)",
                    (profile_id, t["tag"], t.get("color")),
                )
            conn.commit()

    return get_profile(profile_id)


def delete_profile(profile_id: str) -> bool:
    with get_db() as conn:
        cursor = conn.execute("DELETE FROM profiles WHERE id = ?", (profile_id,))
        conn.commit()
        return cursor.rowcount > 0


def create_proxy_endpoint(
    protocol: str,
    host: str,
    port: int,
    name: str | None = None,
    username: str | None = None,
    password: str | None = None,
    region: str | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    if protocol not in {"http", "https", "socks5"}:
        raise ValueError("protocol must be one of: http, https, socks5")
    if not host.strip():
        raise ValueError("host is required")
    if port < 1 or port > 65535:
        raise ValueError("port must be between 1 and 65535")
    proxy_id = str(uuid.uuid4())
    now = _now()
    with get_db() as conn:
        duplicate = conn.execute(
            """SELECT id FROM proxy_endpoints
            WHERE protocol = ? AND host = ? AND port = ? AND username IS ?""",
            (protocol, host, port, username),
        ).fetchone()
        if duplicate:
            raise sqlite3.IntegrityError("duplicate proxy endpoint")
        conn.execute(
            """INSERT INTO proxy_endpoints (
                id, name, protocol, host, port, username, password, region,
                tags, health, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                proxy_id,
                name or f"{protocol}://{host}:{port}",
                protocol,
                host,
                port,
                username,
                password,
                region,
                json.dumps(tags or []),
                "unknown",
                now,
                now,
            ),
        )
        conn.commit()
    return get_proxy_endpoint(proxy_id)  # type: ignore[return-value]


def get_proxy_endpoint(proxy_id: str) -> dict[str, Any] | None:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM proxy_endpoints WHERE id = ?", (proxy_id,)).fetchone()
        if not row:
            return None
        return _decode_proxy(dict(row), redact=True)


def get_proxy_endpoint_for_runtime(proxy_id: str) -> dict[str, Any] | None:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM proxy_endpoints WHERE id = ?", (proxy_id,)).fetchone()
        if not row:
            return None
        return _decode_proxy(dict(row), redact=False)


def list_proxy_endpoints() -> list[dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM proxy_endpoints ORDER BY created_at DESC").fetchall()
        return [_decode_proxy(dict(row), redact=True) for row in rows]


def select_proxy_endpoint() -> dict[str, Any] | None:
    with get_db() as conn:
        row = conn.execute(
            """SELECT * FROM proxy_endpoints
            WHERE health != 'unhealthy'
            ORDER BY created_at ASC
            LIMIT 1"""
        ).fetchone()
        if not row:
            return None
        return _decode_proxy(dict(row), redact=False)


def import_proxy_csv(csv_text: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    created: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    reader = csv.DictReader(io.StringIO(csv_text))
    for line, row in enumerate(reader, start=2):
        try:
            created.append(
                create_proxy_endpoint(
                    protocol=(row.get("protocol") or "http").strip(),
                    host=(row.get("host") or "").strip(),
                    port=int(row.get("port") or "0"),
                    name=(row.get("name") or "").strip() or None,
                    username=(row.get("username") or "").strip() or None,
                    password=row.get("password") or None,
                    region=(row.get("region") or "").strip() or None,
                    tags=[tag.strip() for tag in (row.get("tags") or "").split(",") if tag.strip()],
                )
            )
        except sqlite3.IntegrityError:
            errors.append({"line": line, "error": "duplicate proxy endpoint"})
        except Exception as exc:
            errors.append({"line": line, "error": str(exc)})
    return created, errors


def create_task(
    profile_id: str,
    authorized_target: str,
    task_type: str,
    timeout_seconds: int,
    url: str | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    task_id = str(uuid.uuid4())
    now = _now()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO tasks (
                id, profile_id, authorized_target, task_type, url, payload_json, status,
                timeout_seconds, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (task_id, profile_id, authorized_target, task_type, url, json.dumps(payload or {}), "queued", timeout_seconds, now, now),
        )
        conn.commit()
    return get_task(task_id)  # type: ignore[return-value]


def get_task(task_id: str) -> dict[str, Any] | None:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return _task_from_row(row) if row else None


def list_tasks() -> list[dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM tasks ORDER BY created_at DESC").fetchall()
        return [_task_from_row(row) for row in rows]


def next_queued_task() -> dict[str, Any] | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM tasks WHERE status = 'queued' ORDER BY created_at ASC LIMIT 1"
        ).fetchone()
        return _task_from_row(row) if row else None


def update_task(task_id: str, **fields: Any) -> dict[str, Any] | None:
    if not fields:
        return get_task(task_id)
    if "payload" in fields:
        fields["payload_json"] = json.dumps(fields.pop("payload") or {})
    fields["updated_at"] = _now()
    cols = [f"{key} = ?" for key in fields]
    vals = list(fields.values()) + [task_id]
    with get_db() as conn:
        conn.execute(f"UPDATE tasks SET {', '.join(cols)} WHERE id = ?", vals)
        conn.commit()
    return get_task(task_id)


def _task_from_row(row: sqlite3.Row) -> dict[str, Any]:
    task = dict(row)
    try:
        task["payload"] = json.loads(task.pop("payload_json") or "{}")
    except json.JSONDecodeError:
        task["payload"] = {}
    return task


def create_profile_run(
    profile_id: str,
    task_id: str | None,
    proxy_id: str | None,
    status: str,
) -> dict[str, Any]:
    run_id = str(uuid.uuid4())
    with get_db() as conn:
        conn.execute(
            """INSERT INTO profile_runs (
                id, profile_id, task_id, proxy_id, status, started_at
            ) VALUES (?, ?, ?, ?, ?, ?)""",
            (run_id, profile_id, task_id, proxy_id, status, _now()),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM profile_runs WHERE id = ?", (run_id,)).fetchone()
        return dict(row)


def update_profile_run(run_id: str, **fields: Any) -> dict[str, Any] | None:
    if not fields:
        with get_db() as conn:
            row = conn.execute("SELECT * FROM profile_runs WHERE id = ?", (run_id,)).fetchone()
            return dict(row) if row else None
    cols = [f"{key} = ?" for key in fields]
    vals = list(fields.values()) + [run_id]
    with get_db() as conn:
        conn.execute(f"UPDATE profile_runs SET {', '.join(cols)} WHERE id = ?", vals)
        conn.commit()
        row = conn.execute("SELECT * FROM profile_runs WHERE id = ?", (run_id,)).fetchone()
        return dict(row) if row else None


def list_profile_runs() -> list[dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM profile_runs ORDER BY started_at DESC").fetchall()
        return [dict(row) for row in rows]


def _decode_proxy(row: dict[str, Any], redact: bool) -> dict[str, Any]:
    row["tags"] = json.loads(row.get("tags") or "[]")
    if redact and row.get("password"):
        row["password"] = "********"
    return row
