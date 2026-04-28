"""Command line client for the CloakBrowser Manager HTTP API."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx


DEFAULT_BASE_URL = "http://localhost:8080"


class ApiError(RuntimeError):
    """Raised when the Manager API returns a non-success response."""


class ManagerClient:
    def __init__(self, base_url: str, token: str | None = None, timeout: float = 30.0) -> None:
        headers = {"Authorization": f"Bearer {token}"} if token else None
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers=headers,
            timeout=timeout,
        )

    def close(self) -> None:
        self._client.close()

    def request(self, method: str, path: str, json_body: dict[str, Any] | None = None) -> Any:
        try:
            response = self._client.request(method, path, json=json_body)
        except httpx.HTTPError as exc:
            raise ApiError(f"Request failed: {exc}") from exc
        if response.status_code >= 400:
            raise ApiError(_format_error(response))
        if not response.content:
            return {"ok": True}
        return response.json()


def _format_error(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        body = response.text
    return f"API error {response.status_code}: {body}"


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


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


def _profile_payload(args: argparse.Namespace, include_name: bool) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if include_name:
        payload["name"] = args.name
    for field in (
        "fingerprint_seed",
        "proxy",
        "timezone",
        "locale",
        "platform",
        "user_agent",
        "screen_width",
        "screen_height",
        "gpu_vendor",
        "gpu_renderer",
        "hardware_concurrency",
        "human_preset",
        "color_scheme",
        "notes",
    ):
        value = getattr(args, field, None)
        if value is not None:
            payload[field] = value
    for field in ("humanize", "headless", "geoip", "clipboard_sync"):
        value = getattr(args, field, None)
        if value is not None:
            payload[field] = value
    if args.launch_arg:
        payload["launch_args"] = args.launch_arg
    if args.tag:
        payload["tags"] = [{"tag": tag} for tag in args.tag]
    payload.update(_load_json_object(args.json_body))
    return payload


def cmd_status(client: ManagerClient, _args: argparse.Namespace) -> Any:
    return client.request("GET", "/api/status")


def cmd_profiles_list(client: ManagerClient, _args: argparse.Namespace) -> Any:
    return client.request("GET", "/api/profiles")


def cmd_profiles_create(client: ManagerClient, args: argparse.Namespace) -> Any:
    return client.request("POST", "/api/profiles", _profile_payload(args, include_name=True))


def cmd_profiles_get(client: ManagerClient, args: argparse.Namespace) -> Any:
    return client.request("GET", f"/api/profiles/{args.profile_id}")


def cmd_profiles_update(client: ManagerClient, args: argparse.Namespace) -> Any:
    return client.request("PUT", f"/api/profiles/{args.profile_id}", _profile_payload(args, include_name=False))


def cmd_profiles_delete(client: ManagerClient, args: argparse.Namespace) -> Any:
    return client.request("DELETE", f"/api/profiles/{args.profile_id}")


def cmd_profiles_launch(client: ManagerClient, args: argparse.Namespace) -> Any:
    return client.request("POST", f"/api/profiles/{args.profile_id}/launch")


def cmd_profiles_stop(client: ManagerClient, args: argparse.Namespace) -> Any:
    return client.request("POST", f"/api/profiles/{args.profile_id}/stop")


def cmd_profiles_status(client: ManagerClient, args: argparse.Namespace) -> Any:
    return client.request("GET", f"/api/profiles/{args.profile_id}/status")


def cmd_profiles_cdp(client: ManagerClient, args: argparse.Namespace) -> Any:
    return client.request("GET", f"/api/profiles/{args.profile_id}/cdp")


def cmd_proxies_list(client: ManagerClient, _args: argparse.Namespace) -> Any:
    return client.request("GET", "/api/proxies")


def cmd_proxies_create(client: ManagerClient, args: argparse.Namespace) -> Any:
    payload = {
        "name": args.name,
        "protocol": args.protocol,
        "host": args.host,
        "port": args.port,
        "username": args.username,
        "password": args.password,
        "region": args.region,
        "tags": _split_csv(args.tags),
    }
    payload.update(_load_json_object(args.json_body))
    return client.request("POST", "/api/proxies", payload)


def cmd_proxies_import(client: ManagerClient, args: argparse.Namespace) -> Any:
    csv_text = Path(args.path).read_text(encoding="utf-8")
    return client.request("POST", "/api/proxies/import", {"csv": csv_text})


def cmd_proxies_template(_client: ManagerClient, _args: argparse.Namespace) -> Any:
    rows = [
        ["protocol", "host", "port", "username", "password", "region", "tags"],
        ["http", "proxy.example.com", "8080", "user", "secret", "us", "residential"],
    ]
    writer = csv.writer(sys.stdout)
    writer.writerows(rows)
    return None


def cmd_tasks_list(client: ManagerClient, _args: argparse.Namespace) -> Any:
    return client.request("GET", "/api/tasks")


def cmd_tasks_create(client: ManagerClient, args: argparse.Namespace) -> Any:
    payload = {
        "profile_id": args.profile_id,
        "authorized_target": args.authorized_target,
        "task_type": args.task_type,
        "url": args.url,
        "timeout_seconds": args.timeout_seconds,
    }
    payload.update(_load_json_object(args.json_body))
    return client.request("POST", "/api/tasks", payload)


def cmd_tasks_cancel(client: ManagerClient, args: argparse.Namespace) -> Any:
    return client.request("POST", f"/api/tasks/{args.task_id}/cancel")


def cmd_runs_list(client: ManagerClient, _args: argparse.Namespace) -> Any:
    return client.request("GET", "/api/runs")


def cmd_scheduler_status(client: ManagerClient, _args: argparse.Namespace) -> Any:
    return client.request("GET", "/api/scheduler/status")


def cmd_scheduler_tick(client: ManagerClient, _args: argparse.Namespace) -> Any:
    return client.request("POST", "/api/scheduler/tick")


def cmd_config_import(client: ManagerClient, _args: argparse.Namespace) -> Any:
    return client.request("POST", "/api/config/import")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cloak-manager", description="CLI for the CloakBrowser Manager API")
    parser.add_argument("--base-url", default=os.environ.get("CLOAK_MANAGER_URL", DEFAULT_BASE_URL))
    parser.add_argument("--token", default=os.environ.get("CLOAK_MANAGER_TOKEN") or os.environ.get("AUTH_TOKEN"))
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--compact", action="store_true", help="Print compact JSON")
    subparsers = parser.add_subparsers(dest="resource", required=True)

    status = subparsers.add_parser("status", help="Show Manager system status")
    status.set_defaults(func=cmd_status)

    profiles = subparsers.add_parser("profiles", aliases=["profile"], help="Manage browser profiles")
    profile_cmds = profiles.add_subparsers(dest="action", required=True)
    _add_profile_commands(profile_cmds)

    proxies = subparsers.add_parser("proxies", aliases=["proxy"], help="Manage proxy endpoints")
    proxy_cmds = proxies.add_subparsers(dest="action", required=True)
    _add_proxy_commands(proxy_cmds)

    tasks = subparsers.add_parser("tasks", aliases=["task"], help="Manage scheduler tasks")
    task_cmds = tasks.add_subparsers(dest="action", required=True)
    _add_task_commands(task_cmds)

    runs = subparsers.add_parser("runs", aliases=["run"], help="List profile runs")
    run_cmds = runs.add_subparsers(dest="action", required=True)
    run_list = run_cmds.add_parser("list", help="List profile runs")
    run_list.set_defaults(func=cmd_runs_list)

    scheduler = subparsers.add_parser("scheduler", help="Inspect or trigger the scheduler")
    scheduler_cmds = scheduler.add_subparsers(dest="action", required=True)
    scheduler_status = scheduler_cmds.add_parser("status", help="Show scheduler status")
    scheduler_status.set_defaults(func=cmd_scheduler_status)
    scheduler_tick = scheduler_cmds.add_parser("tick", help="Run one scheduler tick")
    scheduler_tick.set_defaults(func=cmd_scheduler_tick)

    config = subparsers.add_parser("config", help="Manage external runtime config")
    config_cmds = config.add_subparsers(dest="action", required=True)
    config_import = config_cmds.add_parser("import", help="Import configured files from CONFIG_DIR")
    config_import.set_defaults(func=cmd_config_import)

    return parser


def _add_profile_options(parser: argparse.ArgumentParser, require_name: bool) -> None:
    if require_name:
        parser.add_argument("name")
    else:
        parser.add_argument("--name")
    parser.add_argument("--fingerprint-seed", type=int)
    parser.add_argument("--proxy")
    parser.add_argument("--timezone")
    parser.add_argument("--locale")
    parser.add_argument("--platform", choices=["windows", "macos", "linux"])
    parser.add_argument("--user-agent")
    parser.add_argument("--screen-width", type=int)
    parser.add_argument("--screen-height", type=int)
    parser.add_argument("--gpu-vendor")
    parser.add_argument("--gpu-renderer")
    parser.add_argument("--hardware-concurrency", type=int)
    parser.add_argument("--humanize", action=argparse.BooleanOptionalAction)
    parser.add_argument("--human-preset", choices=["default", "careful"])
    parser.add_argument("--headless", action=argparse.BooleanOptionalAction)
    parser.add_argument("--geoip", action=argparse.BooleanOptionalAction)
    parser.add_argument("--clipboard-sync", action=argparse.BooleanOptionalAction)
    parser.add_argument("--color-scheme", choices=["light", "dark", "no-preference"])
    parser.add_argument("--launch-arg", action="append", default=[])
    parser.add_argument("--notes")
    parser.add_argument("--tag", action="append", default=[])
    parser.add_argument("--json", dest="json_body", help="Extra JSON object or path to a JSON file")


def _add_profile_commands(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    list_cmd = subparsers.add_parser("list", help="List profiles")
    list_cmd.set_defaults(func=cmd_profiles_list)

    create = subparsers.add_parser("create", help="Create a profile")
    _add_profile_options(create, require_name=True)
    create.set_defaults(func=cmd_profiles_create)

    get = subparsers.add_parser("get", help="Get a profile")
    get.add_argument("profile_id")
    get.set_defaults(func=cmd_profiles_get)

    update = subparsers.add_parser("update", help="Update a profile")
    update.add_argument("profile_id")
    _add_profile_options(update, require_name=False)
    update.set_defaults(func=cmd_profiles_update)

    delete = subparsers.add_parser("delete", help="Delete a profile")
    delete.add_argument("profile_id")
    delete.set_defaults(func=cmd_profiles_delete)

    launch = subparsers.add_parser("launch", help="Launch a profile")
    launch.add_argument("profile_id")
    launch.set_defaults(func=cmd_profiles_launch)

    stop = subparsers.add_parser("stop", help="Stop a profile")
    stop.add_argument("profile_id")
    stop.set_defaults(func=cmd_profiles_stop)

    status = subparsers.add_parser("status", help="Show profile status")
    status.add_argument("profile_id")
    status.set_defaults(func=cmd_profiles_status)

    cdp = subparsers.add_parser("cdp", help="Show CDP connection info")
    cdp.add_argument("profile_id")
    cdp.set_defaults(func=cmd_profiles_cdp)


def _add_proxy_commands(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    list_cmd = subparsers.add_parser("list", help="List proxies")
    list_cmd.set_defaults(func=cmd_proxies_list)

    create = subparsers.add_parser("create", help="Create a proxy endpoint")
    create.add_argument("--name")
    create.add_argument("--protocol", choices=["http", "https", "socks5"], default="http")
    create.add_argument("--host", required=True)
    create.add_argument("--port", type=int, required=True)
    create.add_argument("--username")
    create.add_argument("--password")
    create.add_argument("--region")
    create.add_argument("--tags")
    create.add_argument("--json", dest="json_body", help="Extra JSON object or path to a JSON file")
    create.set_defaults(func=cmd_proxies_create)

    import_cmd = subparsers.add_parser("import", help="Import proxies from a CSV file")
    import_cmd.add_argument("path")
    import_cmd.set_defaults(func=cmd_proxies_import)

    template = subparsers.add_parser("template", help="Print a proxy CSV template")
    template.set_defaults(func=cmd_proxies_template)


def _add_task_commands(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    list_cmd = subparsers.add_parser("list", help="List tasks")
    list_cmd.set_defaults(func=cmd_tasks_list)

    create = subparsers.add_parser("create", help="Create a scheduler task")
    create.add_argument("--profile-id", required=True)
    create.add_argument("--authorized-target", required=True)
    create.add_argument("--task-type", choices=["open_url", "external_cdp"], default="open_url")
    create.add_argument("--url")
    create.add_argument("--timeout-seconds", type=int, default=300)
    create.add_argument("--json", dest="json_body", help="Extra JSON object or path to a JSON file")
    create.set_defaults(func=cmd_tasks_create)

    cancel = subparsers.add_parser("cancel", help="Cancel a queued task")
    cancel.add_argument("task_id")
    cancel.set_defaults(func=cmd_tasks_cancel)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    client = ManagerClient(args.base_url, token=args.token, timeout=args.timeout)
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
