from __future__ import annotations

from typing import Any, Awaitable, Callable

from worker_backend.browser_manager import RunningProfile

from .context import AutomationContext
from .errors import AutomationScriptError
from .runner import automation_context
from .scripts.basic import itp_login_ticket_v1, open_url_v1
from .scripts.nol_native_login import nol_native_login_v1

AutomationHandler = Callable[[AutomationContext], Awaitable[dict[str, Any]]]

_REGISTRY: dict[tuple[str, str], AutomationHandler] = {}


def register_template(script_key: str, script_version: str, handler: AutomationHandler) -> None:
    key = (script_key.strip(), script_version.strip() or "v1")
    if not key[0]:
        raise ValueError("script_key is required")
    _REGISTRY[key] = handler


def unregister_template(script_key: str, script_version: str) -> None:
    _REGISTRY.pop((script_key.strip(), script_version.strip() or "v1"), None)


def _register_builtin_templates() -> None:
    register_template("nol_native_login", "v1", nol_native_login_v1)
    register_template("open_url", "v1", open_url_v1)
    register_template("itp_login_ticket", "v1", itp_login_ticket_v1)


def list_templates() -> list[dict[str, str]]:
    return [
        {"script_key": script_key, "script_version": script_version, "input_schema_version": "v1"}
        for script_key, script_version in sorted(_REGISTRY)
    ]


async def run_template(running: RunningProfile, payload: dict[str, Any]) -> dict[str, Any]:
    script_key = str(payload.get("script_key") or "").strip()
    script_version = str(payload.get("script_version") or "v1").strip() or "v1"
    handler = _REGISTRY.get((script_key, script_version))
    if not handler:
        raise ValueError(f"automation template not found: {script_key}@{script_version}")
    async with automation_context(running, payload) as ctx:
        try:
            result = await handler(ctx)
        except AutomationScriptError as exc:
            raise AutomationScriptError(
                str(exc),
                {
                    "script_key": script_key,
                    "script_version": script_version,
                    "result": exc.result,
                },
            ) from exc
    return {
        "script_key": script_key,
        "script_version": script_version,
        "result": result,
    }


_register_builtin_templates()
