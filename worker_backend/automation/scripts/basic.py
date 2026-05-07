from __future__ import annotations

from typing import Any

from worker_backend.automation.context import AutomationContext


async def open_url_v1(ctx: AutomationContext) -> dict[str, Any]:
    url = ctx.target_url()
    await ctx.page.goto(url, wait_until="domcontentloaded", timeout=ctx.timeout_seconds * 1000)
    return {"url": ctx.page.url, "title": await ctx.page.title()}


async def itp_login_ticket_v1(ctx: AutomationContext) -> dict[str, Any]:
    url = ctx.target_url()
    await ctx.page.goto(url, wait_until="domcontentloaded", timeout=ctx.timeout_seconds * 1000)
    return {
        "url": ctx.page.url,
        "title": await ctx.page.title(),
        "account": ctx.params.get("account") or ctx.payload.get("account"),
        "phase": "opened_login_page",
    }
