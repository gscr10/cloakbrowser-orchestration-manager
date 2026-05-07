from __future__ import annotations

import asyncio
import random
import time
from typing import Any
from urllib.parse import urlsplit

from worker_backend.automation.context import AutomationContext
from worker_backend.automation.errors import AutomationScriptError

NOL_LOGIN_URL = "https://world.nol.com/en/auth-web/login?returnUrl=%2Fen%2Fmy-info"


async def _safe_eval(page: Any, expr: str, default: Any = None) -> Any:
    try:
        return await page.evaluate(expr)
    except Exception:
        return default


async def _turnstile_solved(page: Any) -> bool:
    state = await _safe_eval(
        page,
        """() => {
            const widget = document.querySelector('[data-has-token], .cf-turnstile, [data-sitekey]');
            const input = document.querySelector('input[name="cf-turnstile-response"]');
            return {
                tokenAttr: widget ? widget.getAttribute('data-has-token') : null,
                inputLen: input ? input.value.length : 0,
            };
        }""",
        {},
    ) or {}
    return state.get("tokenAttr") == "true" or int(state.get("inputLen") or 0) > 0


async def _click_turnstile_with_locators(page: Any) -> bool:
    for frame in page.frames:
        if "challenges.cloudflare.com" not in (frame.url or ""):
            continue
        for selector in ('input[type="checkbox"]', '[type="checkbox"]', "label", "body"):
            try:
                locator = frame.locator(selector).first
                if await locator.count() == 0:
                    continue
                kwargs: dict[str, Any] = {"timeout": 3000}
                if selector == "body":
                    kwargs["position"] = {"x": random.randint(24, 38), "y": random.randint(22, 36)}
                await locator.click(**kwargs)
                return True
            except Exception:
                continue
    return False


async def _wait_turnstile(page: Any, timeout_seconds: int) -> bool:
    start = time.monotonic()
    clicked = False
    while time.monotonic() - start < timeout_seconds:
        if await _turnstile_solved(page):
            return True
        if not clicked and time.monotonic() - start > 3:
            clicked = await _click_turnstile_with_locators(page)
            if clicked:
                await asyncio.sleep(4)
                continue
        await asyncio.sleep(1)
    return False


async def _verify_login(page: Any, account: str) -> bool:
    current_url = page.url
    path = urlsplit(current_url).path
    try:
        page_text = (await page.locator("body").inner_text(timeout=5000))[:5000]
    except Exception:
        page_text = ""
    still_on_login = "auth-web/login" in path
    on_account_page = "my-info" in path or "my-page" in path
    has_account_content = account in page_text or "Reservations" in page_text or "예약" in page_text
    return (on_account_page or has_account_content) and not still_on_login


async def nol_native_login_v1(ctx: AutomationContext) -> dict[str, Any]:
    account = ctx.account()
    password = str(ctx.params.get("password") or ctx.payload.get("password") or "").strip()
    if not account or not password:
        raise ValueError("nol_native_login_v1 requires account/email and password")

    timeout_ms = max(60000, ctx.timeout_seconds * 1000)
    turnstile_timeout = int(ctx.params.get("auto_turnstile_timeout") or 80)
    require_login = bool(ctx.params.get("require_login", True))
    page = ctx.page
    page.set_default_timeout(30000)
    page.set_default_navigation_timeout(timeout_ms)

    await page.goto(ctx.target_url(NOL_LOGIN_URL), wait_until="domcontentloaded", timeout=timeout_ms)
    webdriver = await _safe_eval(page, "() => navigator.webdriver", "unknown")

    email_input = page.locator('input[name="email"]')
    password_input = page.locator('input[name="password"]')
    await email_input.fill("")
    await email_input.type(account, delay=random.randint(60, 140))
    await password_input.fill("")
    await password_input.type(password, delay=random.randint(70, 160))

    turnstile_ok = await _wait_turnstile(page, turnstile_timeout)
    if turnstile_ok:
        await email_input.fill(account)
        await password_input.fill(password)
        login_button = page.get_by_role("button", name="Log in")
        if await login_button.count() == 0:
            login_button = page.get_by_role("button", name="Login")
        await login_button.click(timeout=10000)
        try:
            await page.wait_for_url("**/my-info**", timeout=25000)
        except Exception:
            try:
                await page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
        await asyncio.sleep(2)

    login_ok = await _verify_login(page, account)
    screenshot_path = ctx.artifact_path("nol-native-login")
    await page.screenshot(path=str(screenshot_path), full_page=True)
    result = {
        "url": page.url,
        "title": await page.title(),
        "account": account,
        "turnstile": turnstile_ok,
        "login": login_ok,
        "webdriver": webdriver,
        "artifacts": [{"type": "screenshot", "uri": str(screenshot_path)}],
    }
    if require_login and not (turnstile_ok and login_ok):
        raise AutomationScriptError(
            f"nol native login failed: turnstile={turnstile_ok}, login={login_ok}, url={page.url}",
            result,
        )
    return result
