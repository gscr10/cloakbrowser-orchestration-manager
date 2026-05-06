#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
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
    _require(any(item.get("script_key") == "open_url" for item in schemas), "open_url input schema is missing")

    worker_templates = None
    worker_profiles = None
    if worker_url:
        worker_templates = _json("GET", worker_url, "/api/automation/templates")
        if isinstance(worker_templates, dict):
            worker_templates = worker_templates.get("templates") or []
        worker_profiles = _json("GET", worker_url, "/api/profiles")
        _require(any(item.get("script_key") == "open_url" for item in worker_templates), "worker open_url template is missing")
        _require(isinstance(worker_profiles, list), "worker profiles endpoint is not healthy")

    task = None
    if not args.skip_task:
        created = _json(
            "POST",
            master_url,
            "/api/master/tasks",
            {
                "authorized_target": args.authorized_target,
                "task_type": "open_url",
                "url": args.url,
                "timeout_seconds": args.task_timeout,
                "max_retries": 0,
            },
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
        "task": task,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Public Master/Worker smoke E2E test")
    parser.add_argument("--master-url", required=True)
    parser.add_argument("--worker-url")
    parser.add_argument("--url", default="https://www.baidu.com/s?wd=BTS")
    parser.add_argument("--authorized-target", default="public e2e open_url")
    parser.add_argument("--task-timeout", type=int, default=180)
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
