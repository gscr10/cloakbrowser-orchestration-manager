#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any
from urllib import error, request


def _json(method: str, base_url: str, path: str, payload: dict[str, Any] | None = None, timeout: float = 10.0) -> Any:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = request.Request(base_url.rstrip("/") + path, data=data, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else None
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} failed: HTTP {exc.code} {body}") from exc


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _poll_task(master_url: str, task_id: str, timeout_seconds: int) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        task = _json("GET", master_url, f"/api/master/tasks/{task_id}")
        status = task.get("status")
        if status in {"success", "failed", "final_failed"}:
            return task
        time.sleep(3)
    raise RuntimeError(f"task {task_id} did not finish within {timeout_seconds}s")


def _redact_secret(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: ("***" if key.lower() in {"password", "secret", "token"} else _redact_secret(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_secret(item) for item in value]
    return value


def run(args: argparse.Namespace) -> dict[str, Any]:
    master_url = args.master_url.rstrip("/")
    worker_url = args.worker_url.rstrip("/") if args.worker_url else None

    providers = _json("GET", master_url, "/api/master/providers")
    cluster = _json("GET", master_url, "/api/master/cluster/status")
    workers = _json("GET", master_url, "/api/master/infra/workers")
    schemas = _json("GET", master_url, "/api/master/biz/input-schemas")

    _require(isinstance(providers.get("providers"), list), "master providers endpoint is not healthy")
    _require(isinstance(cluster.get("nodes"), list), "master cluster endpoint is not healthy")
    _require(any(node.get("status") == "online" for node in cluster["nodes"]), "no online worker registered in master")
    _require(isinstance(workers, list), "infra workers endpoint is not healthy")
    _require(any(item.get("script_key") == args.script_key for item in schemas), f"{args.script_key} input schema is missing")

    worker_templates = None
    worker_profiles = None
    if worker_url:
        worker_templates = _json("GET", worker_url, "/api/automation/templates")
        if isinstance(worker_templates, dict):
            worker_templates = worker_templates.get("templates") or []
        worker_profiles = _json("GET", worker_url, "/api/profiles")
        _require(any(item.get("script_key") == args.script_key for item in worker_templates), f"worker {args.script_key} template is missing")
        _require(isinstance(worker_profiles, list), "worker profiles endpoint is not healthy")

    task = None
    if not args.skip_task:
        if args.script_key == "nol_native_login":
            _require(bool(args.account), "nol_native_login requires --account or NOL_EMAIL")
            _require(bool(args.password), "nol_native_login requires --password or NOL_PASSWORD")
        biz_params: dict[str, Any] = {
            "account": args.account,
            "password": args.password,
            "timezone": args.timezone,
            "locale": args.locale,
            "minimal_cloak": args.minimal_cloak,
            "humanize": True,
            "human_preset": "careful",
            "use_cdp_automation": True,
            "human_config": {
                "mistype_chance": 0.03,
                "typing_delay": 100,
                "idle_between_actions": True,
                "idle_between_duration": [0.3, 0.8],
            },
            "auto_turnstile_timeout": args.turnstile_timeout,
            "turnstile_page_attempts": args.turnstile_page_attempts,
            "require_login": args.require_login,
        }
        if args.fingerprint_seed is not None:
            biz_params["fingerprint_seed"] = args.fingerprint_seed
        if args.backend:
            biz_params["backend"] = args.backend
        payload = {
            "authorized_target": args.authorized_target,
            "task_type": "automation_script" if args.script_key else "open_url",
            "url": args.url,
            "script_key": args.script_key,
            "script_version": args.script_version,
            "biz_params": biz_params,
            "timeout_seconds": args.task_timeout,
            "max_retries": 0,
        }
        if args.script_key == "open_url":
            payload = {
                "authorized_target": args.authorized_target,
                "task_type": "open_url",
                "url": args.url,
                "timeout_seconds": args.task_timeout,
                "max_retries": 0,
            }
        created = _json(
            "POST",
            master_url,
            "/api/master/tasks",
            payload,
            timeout=15,
        )
        task = _poll_task(master_url, created["id"], args.task_timeout)
        _require(task.get("status") == "success", f"task did not succeed: {task.get('status')} {task.get('failure_reason')}")

    return {
        "master_url": master_url,
        "worker_url": worker_url,
        "online_nodes": [node["node_id"] for node in cluster["nodes"] if node.get("status") == "online"],
        "infra_workers": len(workers),
        "worker_templates": worker_templates,
        "worker_profiles": len(worker_profiles or []),
        "task": _redact_secret(task),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Public Master/Worker smoke E2E test")
    parser.add_argument("--master-url", required=True)
    parser.add_argument("--worker-url")
    parser.add_argument("--url", default="https://world.nol.com/en/auth-web/login?returnUrl=%2Fen%2Fmy-info")
    parser.add_argument("--authorized-target", default="public e2e nol_native_login")
    parser.add_argument("--script-key", default="nol_native_login")
    parser.add_argument("--script-version", default="v1")
    parser.add_argument("--account", default=os.environ.get("NOL_EMAIL", ""))
    parser.add_argument("--password", default=os.environ.get("NOL_PASSWORD", ""))
    env_fingerprint_seed = os.environ.get("FINGERPRINT_SEED")
    parser.add_argument(
        "--fingerprint-seed",
        type=int,
        default=int(env_fingerprint_seed) if env_fingerprint_seed else None,
        help="Optional fixed fingerprint seed. Omit for a random seed per new profile.",
    )
    parser.add_argument("--timezone", default=os.environ.get("NOL_TIMEZONE", "Asia/Shanghai"))
    parser.add_argument("--locale", default=os.environ.get("NOL_LOCALE", "zh-CN"))
    parser.add_argument("--backend", default=os.environ.get("CLOAK_BACKEND"))
    parser.add_argument("--minimal-cloak", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--turnstile-timeout", type=int, default=int(os.environ.get("AUTO_TURNSTILE_TIMEOUT", "80")))
    parser.add_argument("--turnstile-page-attempts", type=int, default=int(os.environ.get("TURNSTILE_PAGE_ATTEMPTS", "2")))
    parser.add_argument("--require-login", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--task-timeout", type=int, default=240)
    parser.add_argument("--skip-task", action="store_true")
    args = parser.parse_args()
    try:
        result = run(args)
    except Exception as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
