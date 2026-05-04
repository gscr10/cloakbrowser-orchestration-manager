from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import database as db

ACTIVE_PROVIDER_KEY = "master.active_provider"
DEFAULT_PROVIDER = "static"
SERVER_LIST_PATH = Path(os.environ.get("MASTER_SERVER_LIST_PATH", "/config/servers.json"))
PROVISION_CONFIG_PATH = Path(os.environ.get("MASTER_PROVISION_CONFIG_PATH", "/config/provision.json"))
PROVISION_TIMEOUT_SECONDS = int(os.environ.get("MASTER_PROVISION_TIMEOUT_SECONDS", "120"))
PROVISION_MAX_PARALLEL = int(os.environ.get("MASTER_PROVISION_MAX_PARALLEL", "4"))
PROVISION_BOOTSTRAP_CMD = os.environ.get("MASTER_PROVISION_BOOTSTRAP_CMD", "set -e; mkdir -p /opt/cloak-manager-worker; docker --version >/dev/null 2>&1")
PROVISION_START_CMD = os.environ.get("MASTER_PROVISION_START_CMD", "set -e; cd /opt/cloak-manager-worker; echo start-worker-placeholder")
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


class FeishuCliProvider(ServerProvider):
    name = "feishu_cli"

    def get_servers(self) -> list[ServerRecord]:
        raise NotImplementedError("feishu_cli provider is reserved and not implemented yet")


def available_providers() -> dict[str, ServerProvider]:
    return {"static": StaticProvider(), "feishu_cli": FeishuCliProvider()}


def get_active_provider_name() -> str:
    return db.get_master_setting(ACTIVE_PROVIDER_KEY) or DEFAULT_PROVIDER


def set_active_provider_name(name: str) -> str:
    if name not in available_providers():
        raise ValueError("provider not supported")
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
    return db.create_master_task(profile_id=payload.get("profile_id"), authorized_target=payload["authorized_target"], task_type=payload["task_type"], payload=payload, timeout_seconds=int(payload.get("timeout_seconds") or 300), max_retries=int(payload.get("max_retries") or 1), target_node_id=target["node_id"] if target else None)


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
        return True, "dry-run"
    bootstrap_cmd = cfg.bootstrap_cmd.format(node_id=record.node_id, host=record.host, username=record.username, max_profiles=record.max_profiles)
    start_cmd = cfg.start_cmd.format(node_id=record.node_id, host=record.host, username=record.username, max_profiles=record.max_profiles)
    remote_cmd = f"{bootstrap_cmd}; {start_cmd}"
    cmd, env = _build_ssh_exec(record, remote_cmd)
    askpass_path = env.get("SSH_ASKPASS") if env else None
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=cfg.timeout_seconds, env=env)
    except Exception as exc:
        return False, str(exc)
    finally:
        if askpass_path:
            try:
                Path(askpass_path).unlink(missing_ok=True)
            except Exception:
                pass
    if proc.returncode != 0:
        return False, (proc.stderr or proc.stdout or "ssh failed").strip()
    return True, (proc.stdout or "ok").strip()


def run_provision(dry_run: bool = True) -> dict[str, Any]:
    cfg = load_provision_config()
    provider = get_active_provider()
    records = [record for record in provider.get_servers() if record.enabled]
    job = db.create_provision_job(provider=provider.name, total_servers=len(records), dry_run=dry_run)
    success_count = 0
    failed_count = 0

    def run_one(record: ServerRecord) -> tuple[ServerRecord, bool, str]:
        ok, message = execute_provision(record, dry_run=dry_run, cfg=cfg)
        if ok and not dry_run:
            verified, verify_msg = verify_node_registered(record.node_id, job.get("created_at"), cfg.verify_wait_seconds, cfg.verify_interval_seconds)
            ok = verified
            message = f"{message}; {verify_msg}"
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
