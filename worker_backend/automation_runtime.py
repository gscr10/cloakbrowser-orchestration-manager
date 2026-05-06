from __future__ import annotations

from typing import Any, Awaitable, Callable

from .browser_manager import RunningProfile

AutomationHandler = Callable[[RunningProfile, dict[str, Any]], Awaitable[dict[str, Any]]]


async def _open_url_v1(running: RunningProfile, payload: dict[str, Any]) -> dict[str, Any]:
    url = payload.get("target_url") or payload.get("url") or (payload.get("biz_params") or {}).get("target_url")
    if not url:
        raise ValueError("open_url_v1 requires target_url or url")
    page = running.context.pages[0] if running.context.pages else await running.context.new_page()
    await page.goto(str(url), wait_until="domcontentloaded", timeout=int(payload.get("timeout_seconds") or 300) * 1000)
    return {"url": page.url, "title": await page.title()}


async def _itp_login_ticket_v1(running: RunningProfile, payload: dict[str, Any]) -> dict[str, Any]:
    params = payload.get("biz_params") or {}
    target_url = payload.get("target_url") or payload.get("url") or params.get("target_url")
    if not target_url:
        raise ValueError("itp_login_ticket_v1 requires target_url")
    page = running.context.pages[0] if running.context.pages else await running.context.new_page()
    await page.goto(str(target_url), wait_until="domcontentloaded", timeout=int(payload.get("timeout_seconds") or 300) * 1000)
    # The concrete site flow will be filled in later; the template contract is now stable.
    return {
        "url": page.url,
        "title": await page.title(),
        "account": params.get("account") or payload.get("account"),
        "phase": "opened_login_page",
    }


_REGISTRY: dict[tuple[str, str], AutomationHandler] = {
    ("open_url", "v1"): _open_url_v1,
    ("itp_login_ticket", "v1"): _itp_login_ticket_v1,
}


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
    result = await handler(running, payload)
    return {
        "script_key": script_key,
        "script_version": script_version,
        "result": result,
    }
