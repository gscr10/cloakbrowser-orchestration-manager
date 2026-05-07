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
from . import feishu_contract
from . import infra_repository
from . import source_registry


def _shell_join(*parts: str) -> str:
    return " ".join(part.strip().replace("\n", " ") for part in parts if part.strip())


ACTIVE_PROVIDER_KEY = "master.active_provider"
DEFAULT_PROVIDER = "static"
SERVER_LIST_PATH = Path(os.environ.get("MASTER_SERVER_LIST_PATH", "/config/servers.json"))
PROVISION_CONFIG_PATH = Path(os.environ.get("MASTER_PROVISION_CONFIG_PATH", "/config/provision.json"))
PROVISION_TIMEOUT_SECONDS = int(os.environ.get("MASTER_PROVISION_TIMEOUT_SECONDS", "120"))
PROVISION_MAX_PARALLEL = int(os.environ.get("MASTER_PROVISION_MAX_PARALLEL", "4"))
PROVISION_WORKER_IMAGE = os.environ.get("MASTER_PROVISION_WORKER_IMAGE", "ghcr.io/gscr10/cloakbrowser-orchestration-manager-worker:latest")
PROVISION_REPO_URL = os.environ.get("MASTER_PROVISION_REPO_URL", "https://github.com/gscr10/cloakbrowser-orchestration-manager.git")
PROVISION_REPO_REF = os.environ.get("MASTER_PROVISION_REPO_REF", "main")
PROVISION_WORKER_SOURCE_DIR = os.environ.get("MASTER_PROVISION_WORKER_SOURCE_DIR", "/opt/cloakbrowser-orchestration-manager")
PROVISION_WORKER_CONFIG_DIR = os.environ.get("MASTER_PROVISION_WORKER_CONFIG_DIR", "/opt/cloak-manager-worker/config")
# The fallback default is only for local Docker debugging; public deployments
# should always set MASTER_PROVISION_MASTER_BASE_URL explicitly.
PROVISION_MASTER_BASE_URL = os.environ.get("MASTER_PROVISION_MASTER_BASE_URL", "http://host.docker.internal:8080")
PROVISION_WORKER_API_BASE = os.environ.get("MASTER_PROVISION_WORKER_API_BASE", "http://{host}:8080")
PROVISION_REMOTE_PREAMBLE = _shell_join(
    "set -eu;",
    'fail() {{ code="$1"; msg="$2"; echo "PROVISION_ERROR[$code]: $msg" >&2; exit 1; }};',
    'as_root() {{ if [ "$(id -u)" -eq 0 ]; then "$@"; elif sudo -n true >/dev/null 2>&1; then sudo -n "$@"; else fail sudo_nopasswd "sudo NOPASSWD is required for $*"; fi; }};',
    'ensure_owned_dir() {{ path="$1"; as_root mkdir -p "$path" || fail dir_permission "cannot create $path"; as_root chown "$(id -un):$(id -gn)" "$path" || fail dir_permission "cannot chown $path"; [ -w "$path" ] || fail dir_permission "current user cannot write $path after chown"; }};',
    'ensure_docker() {{ command -v docker >/dev/null 2>&1 || fail docker_missing "docker command is missing"; if docker ps >/dev/null 2>&1; then DOCKER="docker"; elif sudo -n true >/dev/null 2>&1; then if sudo -n docker ps >/dev/null 2>&1; then DOCKER="sudo -n docker"; else fail docker_permission "docker daemon is not accessible through sudo -n docker"; fi; else fail sudo_nopasswd "docker requires sudo but sudo NOPASSWD is not configured"; fi; $DOCKER --version >/dev/null 2>&1 || fail docker_missing "docker command is not usable"; }};',
    'ensure_git() {{ if command -v git >/dev/null 2>&1; then return 0; fi; if [ "$(id -u)" -ne 0 ] && ! sudo -n true >/dev/null 2>&1; then fail sudo_nopasswd "git is missing and sudo NOPASSWD is required to install it"; fi; if command -v dnf >/dev/null 2>&1; then as_root dnf install -y git; elif command -v yum >/dev/null 2>&1; then as_root yum install -y git; elif command -v apt-get >/dev/null 2>&1; then as_root apt-get update && as_root apt-get install -y git; else fail git_missing "git command is missing and no supported package manager was found"; fi; command -v git >/dev/null 2>&1 || fail git_missing "git command is required but could not be installed"; }};',
)
PROVISION_DOCKER_AUTO_CMD = _shell_join(PROVISION_REMOTE_PREAMBLE, "ensure_docker;")
PROVISION_BOOTSTRAP_CMD = os.environ.get(
    "MASTER_PROVISION_BOOTSTRAP_CMD",
    _shell_join(
        PROVISION_REMOTE_PREAMBLE,
        "ensure_owned_dir {config_dir};",
        "ensure_docker;",
        "$DOCKER pull {worker_image}",
    ),
)
PROVISION_START_CMD = os.environ.get(
    "MASTER_PROVISION_START_CMD",
    _shell_join(
        PROVISION_REMOTE_PREAMBLE,
        "ensure_owned_dir {config_dir};",
        "ensure_docker;",
        "$DOCKER rm -f cloak-manager-worker >/dev/null 2>&1 || true; "
        "$DOCKER run -d --name cloak-manager-worker --restart unless-stopped "
        "--shm-size=512m "
        "--add-host host.docker.internal:host-gateway "
        "-p 8080:8080 "
        "-v cloak-manager-data:/data "
        "-v {config_dir}:/config:ro "
        "-e CONFIG_IMPORT_ON_START=true "
        "-e CONFIG_DIR=/config "
        "-e DISTRIBUTED_WORKER_ENABLED=true "
        "-e WORKER_NODE_ID={node_id} "
        "-e WORKER_TAGS={tags_csv} "
        "-e MASTER_BASE_URL={master_base_url} "
        "-e WORKER_API_BASE={worker_api_base} "
        "{worker_image}",
    ),
)
PROVISION_GITHUB_MAIN_BOOTSTRAP_CMD = _shell_join(
    PROVISION_REMOTE_PREAMBLE,
    "ensure_git;",
    "ensure_docker;",
    "as_root rm -rf {source_dir};",
    "ensure_owned_dir {source_dir};",
    "ensure_owned_dir {config_dir};",
    "$DOCKER rm -f cloak-manager-worker >/dev/null 2>&1 || true;",
    "$DOCKER image rm {worker_image} cloak-manager-worker:main >/dev/null 2>&1 || true;",
    "$DOCKER volume rm cloak-manager-data >/dev/null 2>&1 || true;",
    "$DOCKER image prune -f >/dev/null 2>&1 || true;",
    "git clone --branch {repo_ref} --depth 1 {repo_url} {source_dir};",
    "cd {source_dir};",
    "$DOCKER build --pull -t cloak-manager-worker:main -f Dockerfile .",
)
PROVISION_GITHUB_MAIN_START_CMD = _shell_join(
    PROVISION_REMOTE_PREAMBLE,
    "ensure_docker;",
    "ensure_owned_dir {config_dir};",
    "$DOCKER rm -f cloak-manager-worker >/dev/null 2>&1 || true;",
    "$DOCKER run -d --name cloak-manager-worker --restart unless-stopped "
    "--shm-size=512m "
    "--add-host host.docker.internal:host-gateway "
    "-p 8080:8080 "
    "-v cloak-manager-data:/data "
    "-v {config_dir}:/config:ro "
    "-e CONFIG_IMPORT_ON_START=true "
    "-e CONFIG_DIR=/config "
    "-e DISTRIBUTED_WORKER_ENABLED=true "
    "-e WORKER_NODE_ID={node_id} "
    "-e WORKER_TAGS={tags_csv} "
    "-e MASTER_BASE_URL={master_base_url} "
    "-e WORKER_API_BASE={worker_api_base} "
    "cloak-manager-worker:main",
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
        out = []
        source = source_registry.get_infra_source("feishu_openapi")
        for item in source.list_workers():
            from . import infra_sync

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


def available_providers() -> dict[str, ServerProvider]:
    return {"static": StaticProvider(), "local_json": LocalJsonProvider(), "feishu_openapi": FeishuOpenApiProvider()}


def get_active_provider_name() -> str:
    return db.get_master_setting(ACTIVE_PROVIDER_KEY) or DEFAULT_PROVIDER


def set_active_provider_name(name: str) -> str:
    if name not in available_providers():
        raise ValueError("provider not supported")
    if name == "feishu_openapi":
        validation = feishu_contract.validate_config()
        if not validation["ready"]:
            raise ValueError(validation["message"])
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
        mode = str(raw.get("mode") or "image").strip()
        default_bootstrap = PROVISION_GITHUB_MAIN_BOOTSTRAP_CMD if mode in {"github_main", "github_main_clean_rebuild", "clean_rebuild"} else PROVISION_BOOTSTRAP_CMD
        default_start = PROVISION_GITHUB_MAIN_START_CMD if mode in {"github_main", "github_main_clean_rebuild", "clean_rebuild"} else PROVISION_START_CMD
        return ProvisionConfig(timeout_seconds=int(raw.get("timeout_seconds") or PROVISION_TIMEOUT_SECONDS), max_parallel=max(1, int(raw.get("max_parallel") or PROVISION_MAX_PARALLEL)), bootstrap_cmd=str(raw.get("bootstrap_cmd") or default_bootstrap), start_cmd=str(raw.get("start_cmd") or default_start), verify_wait_seconds=int(raw.get("verify_wait_seconds") or PROVISION_VERIFY_WAIT_SECONDS), verify_interval_seconds=float(raw.get("verify_interval_seconds") or PROVISION_VERIFY_INTERVAL_SECONDS))
    return ProvisionConfig(timeout_seconds=PROVISION_TIMEOUT_SECONDS, max_parallel=max(1, PROVISION_MAX_PARALLEL), bootstrap_cmd=PROVISION_BOOTSTRAP_CMD, start_cmd=PROVISION_START_CMD, verify_wait_seconds=PROVISION_VERIFY_WAIT_SECONDS, verify_interval_seconds=PROVISION_VERIFY_INTERVAL_SECONDS)


def _template_values(record: ServerRecord) -> dict[str, str]:
    raw_values = {
        "node_id": record.node_id,
        "host": record.host,
        "username": record.username,
        "max_profiles": str(record.max_profiles),
        "master_base_url": PROVISION_MASTER_BASE_URL,
        "tags_csv": ",".join(record.tags or []),
        "worker_image": PROVISION_WORKER_IMAGE,
        "repo_url": PROVISION_REPO_URL,
        "repo_ref": PROVISION_REPO_REF,
        "source_dir": PROVISION_WORKER_SOURCE_DIR,
        "config_dir": PROVISION_WORKER_CONFIG_DIR,
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


def _classify_provision_failure(message: str) -> str:
    lowered = message.lower()
    if "provision_error[sudo_nopasswd]" in lowered:
        return f"sudo NOPASSWD check failed: {message}"
    if "provision_error[docker_permission]" in lowered:
        return f"docker permission check failed: {message}"
    if "provision_error[docker_missing]" in lowered:
        return f"docker missing check failed: {message}"
    if "provision_error[git_missing]" in lowered:
        return f"git missing check failed: {message}"
    if "provision_error[dir_permission]" in lowered:
        return f"directory permission check failed: {message}"
    if "sudo:" in lowered and ("password" in lowered or "no tty" in lowered):
        return f"sudo NOPASSWD check failed: {message}"
    if "docker" in lowered and ("permission denied" in lowered or "cannot connect" in lowered):
        return f"docker permission check failed: {message}"
    if "git:" in lowered and "not found" in lowered:
        return f"git missing check failed: {message}"
    if "permission denied" in lowered and ("/opt" in lowered or "mkdir" in lowered or "chown" in lowered):
        return f"directory permission check failed: {message}"
    return message


def _parse_ts(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value)
    except ValueError:
        return None


def verify_node_registered(
    node_id: str,
    min_heartbeat_after: str | None,
    wait_seconds: int,
    interval_seconds: float,
    expected_api_base: str | None = None,
    expected_tags: list[str] | None = None,
    require_capabilities: bool = True,
) -> tuple[bool, str]:
    start = time.monotonic()
    min_ts = _parse_ts(min_heartbeat_after)
    expected_tag_set = set(expected_tags or [])
    last_issue = "worker did not register heartbeat in time"
    while time.monotonic() - start < max(1, wait_seconds):
        node = db.get_master_node(node_id)
        if node and node.get("status") == "online":
            hb = _parse_ts(node.get("last_heartbeat_at"))
            if not min_ts or (hb and hb >= min_ts):
                if expected_api_base and (node.get("api_base") or "").rstrip("/") != expected_api_base.rstrip("/"):
                    last_issue = f"worker registered with unexpected api_base: {node.get('api_base')}"
                    time.sleep(max(0.1, interval_seconds))
                    continue
                infra_worker = infra_repository.get_worker(node_id) or {}
                infra_hb = _parse_ts(infra_worker.get("last_heartbeat_at"))
                if min_ts and (not infra_hb or infra_hb < min_ts):
                    last_issue = "worker registered but heartbeat was not received after provision"
                    time.sleep(max(0.1, interval_seconds))
                    continue
                observed_tags = set(node.get("tags") or [])
                observed_tags.update(infra_worker.get("tags") or [])
                if expected_tag_set and not expected_tag_set.issubset(observed_tags):
                    last_issue = f"worker registered without expected tags: {sorted(expected_tag_set - observed_tags)}"
                    time.sleep(max(0.1, interval_seconds))
                    continue
                capabilities = infra_repository.list_capabilities(node_id)
                if require_capabilities and not capabilities:
                    last_issue = "worker registered but did not report capabilities"
                    time.sleep(max(0.1, interval_seconds))
                    continue
                details = [
                    "node registered and heartbeat received",
                    f"api_base={node.get('api_base') or 'unknown'}",
                    f"capabilities={len(capabilities)}",
                ]
                if observed_tags:
                    details.append(f"tags={','.join(sorted(observed_tags))}")
                return True, "; ".join(details)
        time.sleep(max(0.1, interval_seconds))
    return False, last_issue


def _active_task_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    for task in db.list_master_tasks():
        node_id = task.get("target_node_id")
        if node_id and task.get("status") in {"queued", "dispatched", "running"}:
            counts[str(node_id)] = counts.get(str(node_id), 0) + 1
    return counts


def pick_target_node() -> dict[str, Any] | None:
    candidates = []
    now = dt.datetime.now(dt.timezone.utc)
    active_counts = _active_task_counts()
    for node in db.list_master_nodes():
        if node["status"] != "online":
            continue
        hb = _parse_ts(node.get("last_heartbeat_at"))
        if hb and (now - hb).total_seconds() > NODE_HEARTBEAT_TTL_SECONDS:
            continue
        reserved_profiles = active_counts.get(node["node_id"], 0)
        running_profiles = int(node.get("running_profiles") or 0)
        max_profiles = int(node.get("max_profiles") or 15)
        effective_profiles = running_profiles + reserved_profiles
        if effective_profiles >= max_profiles:
            continue
        cpu = float(node.get("cpu_percent") or 0.0)
        mem_total = int(node.get("mem_total_mb") or 0)
        mem_used = int(node.get("mem_used_mb") or 0)
        mem_ratio = (mem_used / mem_total) if mem_total > 0 else 0.0
        if cpu > 95.0 or mem_ratio > 0.95:
            continue
        score = effective_profiles
        candidates.append((score, cpu, mem_ratio, node))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1], item[2]))
    return candidates[0][3]


def create_master_task(payload: dict[str, Any]) -> dict[str, Any]:
    target = pick_target_node()
    target_node_id = payload.get("target_node_id") or (target["node_id"] if target else None)
    max_retries = 1 if payload.get("max_retries") is None else int(payload.get("max_retries") or 0)
    return db.create_master_task(profile_id=payload.get("profile_id"), authorized_target=payload["authorized_target"], task_type=payload["task_type"], payload=payload, timeout_seconds=int(payload.get("timeout_seconds") or 300), max_retries=max_retries, target_node_id=target_node_id, priority=int(payload.get("priority") or 0))


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
        message = _classify_provision_failure((proc.stderr or proc.stdout or "ssh failed").strip())
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
            values = _template_values(record)
            verified, verify_msg = verify_node_registered(
                record.node_id,
                job.get("created_at"),
                cfg.verify_wait_seconds,
                cfg.verify_interval_seconds,
                expected_api_base=shlex.split(values["worker_api_base"])[0] if values.get("worker_api_base") else None,
                expected_tags=record.tags or [],
                require_capabilities=True,
            )
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
