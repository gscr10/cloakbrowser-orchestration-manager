from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Awaitable, Callable

from worker_backend.browser_manager import RunningProfile

from .context import AutomationContext


async def _noop() -> None:
    return None


async def _new_page_session(
    running: RunningProfile,
    payload: dict[str, Any],
    params: dict[str, Any],
) -> tuple[Any, Callable[[], Awaitable[None]]]:
    if not bool(params.get("use_cdp_automation", True)):
        return await running.context.new_page(), _noop

    from playwright.async_api import async_playwright

    pw = await async_playwright().start()
    try:
        cdp_url = f"http://127.0.0.1:{running.cdp_port}"
        seed = params.get("fingerprint_seed") or payload.get("fingerprint_seed")
        if seed is not None:
            cdp_url = f"{cdp_url}?fingerprint={seed}"
        browser = await pw.chromium.connect_over_cdp(cdp_url)
        context = browser.contexts[0] if browser.contexts else await browser.new_context()
        return await context.new_page(), pw.stop
    except Exception:
        await pw.stop()
        raise


@asynccontextmanager
async def automation_context(
    running: RunningProfile,
    payload: dict[str, Any],
) -> AsyncIterator[AutomationContext]:
    params = payload.get("biz_params") if isinstance(payload.get("biz_params"), dict) else {}
    page, cleanup = await _new_page_session(running, payload, params)
    try:
        yield AutomationContext(running=running, payload=payload, params=params, page=page)
    finally:
        await cleanup()
