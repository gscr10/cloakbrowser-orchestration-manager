from __future__ import annotations

import datetime as dt
import json
import os
import shlex
import shutil
import subprocess
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from . import database as db
from . import infra_repository

ACTIVE_PROVIDER_KEY = "master.active_provider"
DEFAULT_PROVIDER = "static"
SERVER_LIST_PATH = Path(os.environ.get("MASTER_SERVER_LIST_PATH", "/config/servers.json"))
PROVISION_CONFIG_PATH = Path(os.environ.get("MASTER_PROVISION_CONFIG_PATH", "/config/provision.json"))
PROVISION_TIMEOUT_SECONDS = int(os.environ.get("MASTER_PROVISION_TIMEOUT_SECONDS", "120"))
PROVISION_MAX_PARALLEL = int(os.environ.get("MASTER_PROVISION_MAX_PARALLEL", "4"))
PROVISION_WORKER_IMAGE = os.environ.get("MASTER_PROVISION_WORKER_IMAGE", "ghcr.io/gscr10/cloakbrowser-orchestration-manager-worker:latest")
# The fallback default is only for local Docker debugging; public deployments
# should always set MASTER_PROVISION_MASTER_BASE_URL explicitly.
PROVISION_MASTER_BASE_URL = os.environ.get("MASTER_PROVISION_MASTER_BASE_URL", "http://host.docker.internal:8080")
PROVISION_WORKER_API_BASE = os.environ.get("MASTER_PROVISION_WORKER_API_BASE", "http://{host}:8080")
PROVISION_DOCKER_AUTO_CMD = (
    'DOCKER="docker"; '
    'docker ps >/dev/null 2>&1 || DOCKER="sudo -n docker"; '
    "$DOCKER --version >/dev/null 2>&1"
)
PROVISION_BOOTSTRAP_CMD = os.environ.get(
    "MASTER_PROVISION_BOOTSTRAP_CMD",
    f"set -e; mkdir -p /opt/cloak-manager-worker/config; {PROVISION_DOCKER_AUTO_CMD}; $DOCKER pull {PROVISION_WORKER_IMAGE}",
)
PROVISION_START_CMD = os.environ.get(
    "MASTER_PROVISION_START_CMD",
    "set -e; "
    f"{PROVISION_DOCKER_AUTO_CMD}; "
    "$DOCKER rm -f cloak-manager-worker >/dev/null 2>&1 || true; "
    "$DOCKER run -d --name cloak-manager-worker --restart unless-stopped "
    "--shm-size=512m "
    "--add-host host.docker.internal:host-gateway "
    "-p 8080:8080 "
    "-v cloak-manager-data:/data "
    "-v /opt/cloak-manager-worker/config:/config:ro "
    "-e CONFIG_IMPORT_ON_START=true "
    "-e CONFIG_DIR=/config "
    "-e DISTRIBUTED_WORKER_ENABLED=true "
    "-e WORKER_NODE_ID={node_id} "
    "-e MASTER_BASE_URL={master_base_url} "
    "-e WORKER_API_BASE={worker_api_base} "
    f"{PROVISION_WORKER_IMAGE}",
)
PROVISION_VERIFY_WAIT_SECONDS = int(os.environ.get("MASTER_PROVISION_VERIFY_WAIT_SECONDS", "30"))
PROVISION_VERIFY_INTERVAL_SECONDS = float(os.environ.get("MASTER_PROVISION_VERIFY_INTERVAL_SECONDS", "2"))
NODE_HEARTBEAT_TTL_SECONDS = int(os.environ.get("MASTER_NODE_HEARTBEAT_TTL_SECONDS", "30"))


@dataclass
class ProvisionConfig:
    timeout_seconds: int
    max_parallel: int
    bootstrap_cmd: str
    start_cmd: str
    verify_wait_seconds: int
    verify_interval_seconds: float


@dataclass
class ServerRecord:
    node_id: str
    host: str
    username: str
    port: int = 22
    password: str | None = None
    max_profiles: int = 15
    tags: list[str] | None = None
    enabled: bool = True


class ServerProvider:
    name = "base"

    def get_servers(self) -> list[ServerRecord]:
        raise NotImplementedError


class StaticProvider(ServerProvider):
    name = "static"

    def get_servers(self) -> list[ServerRecord]:
        if not SERVER_LIST_PATH.exists():
            return []
        data = json.loads(SERVER_LIST_PATH.read_text(encoding="utf-8"))
        records = data.get("servers", []) if isinstance(data, dict) else data
        out = []
        for item in records:
            node_id = str(item.get("node_id") or item.get("host") or "").strip()
            host = str(item.get("host") or "").strip()
            username = str(item.get("username") or "root").strip() or "root"
            if not node_id or not host:
                continue
            out.append(ServerRecord(node_id=node_id, host=host, username=username, port=int(item.get("port") or 22), password=item.get("password"), max_profiles=int(item.get("max_profiles") or 15), tags=item.get("tags") or [], enabled=bool(item.get("enabled", True))))
        return out


class LocalJsonProvider(ServerProvider):
    name = "local_json"

    def get_servers(self) -> list[ServerRecord]:
        from . import infra_sync

        out = []
        for item in infra_sync.local_infra_workers():
            normalized = infra_sync.normalize_worker_record(item)
            if not normalized:
                continue
            out.append(
                ServerRecord(
                    node_id=normalized["node_id"],
                    host=normalized["host"],
                    username=normalized["ssh_user"],
                    port=normalized["ssh_port"],
                    password=normalized.get("ssh_password"),
                    max_profiles=normalized["max_profiles"],
                    tags=normalized.get("tags") or [],
                    enabled=bool(normalized.get("enabled", True)),
                )
            )
        return out


class FeishuOpenApiProvider(ServerProvider):
    name = "feishu_openapi"

    def get_servers(self) -> list[ServerRecord]:
        raise NotImplementedError("feishu_openapi provider is not configured yet")


def available_providers() -> dict[str, ServerProvider]:
    return {"static": StaticProvider(), "local_json": LocalJsonProvider(), "feishu_openapi": FeishuOpenApiProvider()}


def get_active_provider_name() -> str:
    return db.get_master_setting(ACTIVE_PROVIDER_KEY) or DEFAULT_PROVIDER


def set_active_provider_name(name: str) -> str:
    if name not in available_providers():
        raise ValueError("provider not supported")
    if name == "feishu_openapi":
        raise ValueError("feishu_openapi provider is not configured yet")
    db.set_master_setting(ACTIVE_PROVIDER_KEY, name)
    return name


def get_active_provider() -> ServerProvider:
    providers = available_providers()
    name = get_active_provider_name()
    if name not in providers:
        db.set_master_setting(ACTIVE_PROVIDER_KEY, DEFAULT_PROVIDER)
        return providers[DEFAULT_PROVIDER]
    return providers[name]


def load_provision_config() -> ProvisionConfig:
    if PROVISION_CONFIG_PATH.exists():
        raw = json.loads(PROVISION_CONFIG_PATH.read_text(encoding="utf-8"))
        return ProvisionConfig(timeout_seconds=int(raw.get("timeout_seconds") or PROVISION_TIMEOUT_SECONDS), max_parallel=max(1, int(raw.get("max_parallel") or PROVISION_MAX_PARALLEL)), bootstrap_cmd=str(raw.get("bootstrap_cmd") or PROVISION_BOOTSTRAP_CMD), start_cmd=str(raw.get("start_cmd") or PROVISION_START_CMD), verify_wait_seconds=int(raw.get("verify_wait_seconds") or PROVISION_VERIFY_WAIT_SECONDS), verify_interval_seconds=float(raw.get("verify_interval_seconds") or PROVISION_VERIFY_INTERVAL_SECONDS))
    return ProvisionConfig(timeout_seconds=PROVISION_TIMEOUT_SECONDS, max_parallel=max(1, PROVISION_MAX_PARALLEL), bootstrap_cmd=PROVISION_BOOTSTRAP_CMD, start_cmd=PROVISION_START_CMD, verify_wait_seconds=PROVISION_VERIFY_WAIT_SECONDS, verify_interval_seconds=PROVISION_VERIFY_INTERVAL_SECONDS)


def _template_values(record: ServerRecord) -> dict[str, str]:
    raw_values = {
        "node_id": record.node_id,
        "host": record.host,
        "username": record.username,
        "max_profiles": str(record.max_profiles),
        "master_base_url": PROVISION_MASTER_BASE_URL,
    }
    worker_api_base = PROVISION_WORKER_API_BASE.format(**raw_values)
    raw_values["worker_api_base"] = worker_api_base
    return {key: shlex.quote(str(value)) for key, value in raw_values.items()}


def _record_provision_target(record: ServerRecord, provider_name: str, status: str) -> None:
    raw_values = {
        "node_id": record.node_id,
        "host": record.host,
        "username": record.username,
        "max_profiles": str(record.max_profiles),
        "master_base_url": PROVISION_MASTER_BASE_URL,
    }
    worker_api_base = PROVISION_WORKER_API_BASE.format(**raw_values)
    infra_repository.upsert_worker(
        {
            "node_id": record.node_id,
            "source": provider_name,
            "source_record_id": record.node_id,
            "host": record.host,
            "ssh_user": record.username,
            "ssh_password": record.password,
            "ssh_port": record.port,
            "enabled": record.enabled,
            "desired_state": "active" if record.enabled else "disabled",
            "status": status,
            "max_profiles": record.max_profiles,
            "tags": record.tags or [],
            "worker_api_base": worker_api_base,
        }
    )


def _parse_ts(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value)
    except ValueError:
        return None


def verify_node_registered(node_id: str, min_heartbeat_after: str | None, wait_seconds: int, interval_seconds: float) -> tuple[bool, str]:
    start = time.monotonic()
    min_ts = _parse_ts(min_heartbeat_after)
    while time.monotonic() - start < max(1, wait_seconds):
        node = db.get_master_node(node_id)
        if node and node.get("status") == "online":
            hb = _parse_ts(node.get("last_heartbeat_at"))
            if not min_ts or (hb and hb >= min_ts):
                return True, "node registered and heartbeat received"
        time.sleep(max(0.1, interval_seconds))
    return False, "worker did not register heartbeat in time"


def pick_target_node() -> dict[str, Any] | None:
    candidates = []
    now = dt.datetime.now(dt.timezone.utc)
    for node in db.list_master_nodes():
        if node["status"] != "online":
            continue
        hb = _parse_ts(node.get("last_heartbeat_at"))
        if hb and (now - hb).total_seconds() > NODE_HEARTBEAT_TTL_SECONDS:
            continue
        if int(node.get("running_profiles") or 0) >= int(node.get("max_profiles") or 15):
            continue
        cpu = float(node.get("cpu_percent") or 0.0)
        mem_total = int(node.get("mem_total_mb") or 0)
        mem_used = int(node.get("mem_used_mb") or 0)
        mem_ratio = (mem_used / mem_total) if mem_total > 0 else 0.0
        if cpu > 95.0 or mem_ratio > 0.95:
            continue
        score = int(node.get("running_profiles") or 0)
        candidates.append((score, cpu, mem_ratio, node))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1], item[2]))
    return candidates[0][3]


def create_master_task(payload: dict[str, Any]) -> dict[str, Any]:
    target = pick_target_node()
    target_node_id = payload.get("target_node_id") or (target["node_id"] if target else None)
    return db.create_master_task(profile_id=payload.get("profile_id"), authorized_target=payload["authorized_target"], task_type=payload["task_type"], payload=payload, timeout_seconds=int(payload.get("timeout_seconds") or 300), max_retries=int(payload.get("max_retries") or 1), target_node_id=target_node_id)


def _fetch_worker_profile_id(node: dict[str, Any], preferred_name: str | None = None, timeout_seconds: float = 5.0) -> str | None:
    api_base = (node.get("api_base") or "").strip().rstrip("/")
    if not api_base:
        return None
    try:
        with httpx.Client(base_url=api_base, timeout=timeout_seconds) as client:
            resp = client.get("/api/profiles")
            resp.raise_for_status()
            profiles = resp.json()
    except Exception:
        return None
    if not isinstance(profiles, list):
        return None
    reusable_profiles = [
        item
        for item in profiles
        if isinstance(item, dict)
        and isinstance(item.get("id"), str)
        and item.get("id")
        and item.get("status") not in {"running", "starting"}
    ]
    if preferred_name:
        for item in reusable_profiles:
            if item.get("name") == preferred_name:
                return item["id"]
        return None
    for item in reusable_profiles:
        return item["id"]
    return None


def _profile_create_options(payload: dict[str, Any]) -> dict[str, Any]:
    params = payload.get("biz_params") if isinstance(payload.get("biz_params"), dict) else {}
    options = params.get("profile_options") if isinstance(params.get("profile_options"), dict) else {}
    allowed_fields = {
        "fingerprint_seed",
        "proxy",
        "timezone",
        "locale",
        "platform",
        "screen_width",
        "screen_height",
        "humanize",
        "human_preset",
        "human_config",
        "headless",
        "geoip",
        "backend",
        "stealth_args",
        "minimal_cloak",
        "color_scheme",
        "launch_args",
        "notes",
    }
    out = {key: value for key, value in options.items() if key in allowed_fields}
    for key in (
        "fingerprint_seed",
        "proxy",
        "timezone",
        "locale",
        "platform",
        "humanize",
        "human_preset",
        "human_config",
        "headless",
        "backend",
        "stealth_args",
        "minimal_cloak",
    ):
        if key in params and key not in out:
            out[key] = params[key]
    return out


def _create_worker_profile(
    node: dict[str, Any],
    profile_name: str | None = None,
    profile_options: dict[str, Any] | None = None,
    timeout_seconds: float = 8.0,
) -> str | None:
    api_base = (node.get("api_base") or "").strip().rstrip("/")
    if not api_base:
        return None
    node_id = (node.get("node_id") or "worker").strip() or "worker"
    name = (profile_name or "").strip() or f"auto-{node_id}-{uuid.uuid4().hex[:8]}"
    payload = {"name": name, "platform": "windows"}
    payload.update(profile_options or {})
    try:
        with httpx.Client(base_url=api_base, timeout=timeout_seconds) as client:
            resp = client.post("/api/profiles", json=payload)
            resp.raise_for_status()
            body = resp.json()
    except Exception:
        return None
    profile_id = body.get("id") if isinstance(body, dict) else None
    return profile_id if isinstance(profile_id, str) and profile_id else None


def ensure_task_profile_for_node(task: dict[str, Any], node: dict[str, Any]) -> dict[str, Any]:
    if task.get("task_type") not in {"external_cdp", "open_url", "automation_script"}:
        return task
    payload = dict(task.get("payload") or {})
    if (payload.get("profile_id") or "").strip():
        return task
    preferred_name = (payload.get("profile_name") or "").strip() or None
    profile_id = _fetch_worker_profile_id(node, preferred_name=preferred_name)
    if not profile_id:
        profile_id = _create_worker_profile(node, profile_name=preferred_name, profile_options=_profile_create_options(payload))
    if not profile_id:
        return task
    payload["profile_id"] = profile_id
    updated = db.update_master_task(task["id"], profile_id=profile_id, payload_json=json.dumps(payload))
    if updated:
        db.create_master_task_event(task["id"], node.get("node_id"), "profile_auto_selected", f"profile_id={profile_id}")
        return updated
    return task


def _build_ssh_exec(record: ServerRecord, remote_cmd: str) -> tuple[list[str], dict[str, str] | None]:
    if record.password:
        ssh_base = ["ssh", "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=8", "-p", str(record.port), f"{record.username}@{record.host}", remote_cmd]
        sshpass = shutil.which("sshpass")
        if sshpass:
            return [sshpass, "-p", record.password, *ssh_base], None
        with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8", suffix=".sh") as f:
            f.write("#!/bin/sh\n")
            f.write('printf "%s" "$SSH_PASSWORD"\n')
            askpass_path = f.name
        os.chmod(askpass_path, 0o700)
        env = os.environ.copy()
        env["SSH_ASKPASS"] = askpass_path
        env["SSH_ASKPASS_REQUIRE"] = "force"
        env["SSH_PASSWORD"] = record.password
        env["DISPLAY"] = env.get("DISPLAY") or ":0"
        return ["setsid", *ssh_base], env
    return ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "-p", str(record.port), f"{record.username}@{record.host}", remote_cmd], None


def execute_provision(record: ServerRecord, dry_run: bool, cfg: ProvisionConfig) -> tuple[bool, str]:
    if dry_run:
        infra_repository.create_event(record.node_id, "provision_dry_run", "provision dry-run skipped remote execution", "created")
        return True, "dry-run"
    values = _template_values(record)
    bootstrap_cmd = cfg.bootstrap_cmd.format(**values)
    start_cmd = cfg.start_cmd.format(**values)
    remote_cmd = f"{bootstrap_cmd}; {start_cmd}"
    cmd, env = _build_ssh_exec(record, remote_cmd)
    askpass_path = env.get("SSH_ASKPASS") if env else None
    infra_repository.create_event(record.node_id, "provision_started", f"host={record.host}", "created")
    infra_repository.create_event(record.node_id, "ssh_connecting", f"{record.username}@{record.host}:{record.port}", "ssh_connecting")
    infra_repository.create_event(record.node_id, "docker_check", "remote command will auto-detect docker or sudo -n docker", "docker_check")
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=cfg.timeout_seconds, env=env)
    except Exception as exc:
        infra_repository.create_event(record.node_id, "provision_failed", str(exc), "ssh_connecting")
        return False, str(exc)
    finally:
        if askpass_path:
            try:
                Path(askpass_path).unlink(missing_ok=True)
            except Exception:
                pass
    if proc.returncode != 0:
        message = (proc.stderr or proc.stdout or "ssh failed").strip()
        infra_repository.create_event(record.node_id, "provision_failed", message, "remote_command")
        return False, message
    infra_repository.create_event(record.node_id, "worker_container_started", (proc.stdout or "remote command ok").strip(), "container_start")
    return True, (proc.stdout or "ok").strip()


def run_provision(dry_run: bool = True, node_id: str | None = None) -> dict[str, Any]:
    cfg = load_provision_config()
    provider = get_active_provider()
    records = [record for record in provider.get_servers() if record.enabled]
    if node_id:
        records = [record for record in records if record.node_id == node_id]
        if not records:
            raise ValueError(f"provision target not found: {node_id}")
    for record in records:
        _record_provision_target(record, provider.name, "pending_deploy" if dry_run else "deploying")
    job = db.create_provision_job(provider=provider.name, total_servers=len(records), dry_run=dry_run)
    success_count = 0
    failed_count = 0

    def run_one(record: ServerRecord) -> tuple[ServerRecord, bool, str]:
        ok, message = execute_provision(record, dry_run=dry_run, cfg=cfg)
        if ok and not dry_run:
            infra_repository.create_event(record.node_id, "wait_heartbeat", "waiting for worker registration heartbeat", "wait_heartbeat")
            verified, verify_msg = verify_node_registered(record.node_id, job.get("created_at"), cfg.verify_wait_seconds, cfg.verify_interval_seconds)
            ok = verified
            message = f"{message}; {verify_msg}"
            infra_repository.create_event(
                record.node_id,
                "provision_success" if ok else "provision_failed",
                verify_msg,
                "wait_heartbeat",
            )
        return record, ok, message

    max_workers = min(max(1, cfg.max_parallel), max(1, len(records)))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(run_one, record) for record in records]
        for future in as_completed(futures):
            record, ok, message = future.result()
            db.add_provision_job_item(job["id"], record.node_id, record.host, "success" if ok else "failed", message)
            if ok:
                success_count += 1
            else:
                failed_count += 1
    status = "success" if failed_count == 0 else ("failed" if success_count == 0 else "partial_success")
    updated = db.update_provision_job(job["id"], status=status, success_count=success_count, failed_count=failed_count)
    return {"job": updated, "items": db.list_provision_job_items(job["id"])}


def list_servers() -> list[dict[str, Any]]:
    provider = get_active_provider()
    out: list[dict[str, Any]] = []
    for record in provider.get_servers():
        out.append(
            {
                "node_id": record.node_id,
                "host": record.host,
                "username": record.username,
                "port": record.port,
                "max_profiles": record.max_profiles,
                "tags": record.tags or [],
                "enabled": bool(record.enabled),
            }
        )
    return out
