"""Command line client for the independent Master API."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx

DEFAULT_BASE_URL = "http://localhost:8080"


class ApiError(RuntimeError):
    pass


class MasterClient:
    def __init__(self, base_url: str, token: str | None = None, timeout: float = 30.0) -> None:
        headers = {"Authorization": f"Bearer {token}"} if token else None
        self._client = httpx.Client(base_url=base_url.rstrip("/"), headers=headers, timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def request(self, method: str, path: str, json_body: dict[str, Any] | None = None) -> Any:
        try:
            resp = self._client.request(method, path, json=json_body)
        except httpx.HTTPError as exc:
            raise ApiError(f"Request failed: {exc}") from exc
        if resp.status_code >= 400:
            try:
                body = resp.json()
            except ValueError:
                body = resp.text
            raise ApiError(f"API error {resp.status_code}: {body}")
        return resp.json() if resp.content else {"ok": True}


def _load_json_object(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    source = value
    path = Path(value)
    if path.exists():
        source = path.read_text(encoding="utf-8")
    data = json.loads(source)
    if not isinstance(data, dict):
        raise argparse.ArgumentTypeError("JSON body must be an object")
    return data


def cmd_nodes(client: MasterClient, _args: argparse.Namespace) -> Any:
    return client.request("GET", "/api/master/nodes")


def cmd_cluster(client: MasterClient, _args: argparse.Namespace) -> Any:
    return client.request("GET", "/api/master/cluster/status")


def cmd_tasks(client: MasterClient, _args: argparse.Namespace) -> Any:
    return client.request("GET", "/api/master/tasks")


def cmd_task(client: MasterClient, args: argparse.Namespace) -> Any:
    return client.request("GET", f"/api/master/tasks/{args.task_id}")


def cmd_task_events(client: MasterClient, args: argparse.Namespace) -> Any:
    return client.request("GET", f"/api/master/tasks/{args.task_id}/events")


def cmd_create_task(client: MasterClient, args: argparse.Namespace) -> Any:
    payload = {
        "profile_id": args.profile_id,
        "authorized_target": args.authorized_target,
        "task_type": args.task_type,
        "url": args.url.strip() if args.url else None,
        "timeout_seconds": args.timeout_seconds,
        "max_retries": args.max_retries,
    }
    payload.update(_load_json_object(args.json_body))
    return client.request("POST", "/api/master/tasks", payload)


def cmd_providers(client: MasterClient, _args: argparse.Namespace) -> Any:
    return client.request("GET", "/api/master/providers")


def cmd_set_provider(client: MasterClient, args: argparse.Namespace) -> Any:
    if args.provider == "feishu_cli":
        raise ApiError("feishu_cli provider is reserved and not implemented yet")
    return client.request("PUT", "/api/master/providers/active", {"provider": args.provider})


def cmd_provision_run(client: MasterClient, args: argparse.Namespace) -> Any:
    return client.request("POST", "/api/master/provision/run", {"dry_run": args.dry_run})


def cmd_provision_jobs(client: MasterClient, _args: argparse.Namespace) -> Any:
    return client.request("GET", "/api/master/provision/jobs")


def cmd_provision_job(client: MasterClient, args: argparse.Namespace) -> Any:
    return client.request("GET", f"/api/master/provision/jobs/{args.job_id}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cloak-master", description="CLI for independent master backend")
    parser.add_argument("--base-url", default=os.environ.get("CLOAK_MASTER_URL", DEFAULT_BASE_URL))
    parser.add_argument("--token", default=os.environ.get("CLOAK_MASTER_TOKEN") or os.environ.get("AUTH_TOKEN"))
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--compact", action="store_true")
    subparsers = parser.add_subparsers(dest="action", required=True)

    nodes = subparsers.add_parser("nodes")
    nodes.set_defaults(func=cmd_nodes)

    cluster = subparsers.add_parser("cluster")
    cluster.set_defaults(func=cmd_cluster)

    tasks = subparsers.add_parser("tasks")
    tasks.set_defaults(func=cmd_tasks)

    task = subparsers.add_parser("task")
    task.add_argument("task_id")
    task.set_defaults(func=cmd_task)

    task_events = subparsers.add_parser("task-events")
    task_events.add_argument("task_id")
    task_events.set_defaults(func=cmd_task_events)

    create_task = subparsers.add_parser("create-task")
    create_task.add_argument("--profile-id")
    create_task.add_argument("--authorized-target", required=True)
    create_task.add_argument("--task-type", choices=["open_url", "external_cdp"], default="open_url")
    create_task.add_argument("--url")
    create_task.add_argument("--timeout-seconds", type=int, default=300)
    create_task.add_argument("--max-retries", type=int, default=1)
    create_task.add_argument("--json", dest="json_body")
    create_task.set_defaults(func=cmd_create_task)

    providers = subparsers.add_parser("providers")
    providers.set_defaults(func=cmd_providers)

    set_provider = subparsers.add_parser("set-provider")
    set_provider.add_argument("provider", choices=["static", "feishu_cli"])
    set_provider.set_defaults(func=cmd_set_provider)

    provision_run = subparsers.add_parser("provision-run")
    provision_run.add_argument("--dry-run", action=argparse.BooleanOptionalAction, default=True)
    provision_run.set_defaults(func=cmd_provision_run)

    provision_jobs = subparsers.add_parser("provision-jobs")
    provision_jobs.set_defaults(func=cmd_provision_jobs)

    provision_job = subparsers.add_parser("provision-job")
    provision_job.add_argument("job_id")
    provision_job.set_defaults(func=cmd_provision_job)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    if argv is None:
        argv = sys.argv[1:]
    compact_output = "--compact" in argv
    argv = [arg for arg in argv if arg != "--compact"]
    args = parser.parse_args(argv)
    if compact_output:
        args.compact = True

    client = MasterClient(args.base_url, token=args.token, timeout=args.timeout)
    try:
        result = args.func(client, args)
    except (ApiError, json.JSONDecodeError, OSError, argparse.ArgumentTypeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        client.close()

    if result is not None:
        print(json.dumps(result, indent=None if args.compact else 2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
