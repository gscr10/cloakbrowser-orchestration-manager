from __future__ import annotations

import asyncio
import random
import time
from typing import Any
from urllib.parse import urlsplit

from worker_backend.automation.context import AutomationContext
from worker_backend.automation.errors import AutomationScriptError

NOL_LOGIN_URL = "https://world.nol.com/en/auth-web/login?returnUrl=%2Fen%2Fmy-info"
BUY_BUTTON_TEXTS = ("Buy now", "Buy Now", "Buy Presale Tickets", "立即购买")
LOGIN_BUTTON_TEXTS = ("Log in", "Login", "登录")


async def _safe_eval(page: Any, expr: str, default: Any = None, arg: Any = None) -> Any:
    try:
        if arg is not None:
            return await page.evaluate(expr, arg)
        return await page.evaluate(expr)
    except Exception:
        return default


async def _turnstile_solved(page: Any) -> bool:
    state = await _turnstile_state(page)
    return state.get("tokenAttr") == "true" or int(state.get("inputLen") or 0) > 0


async def _turnstile_state(page: Any) -> dict[str, Any]:
    return await _safe_eval(
        page,
        """() => {
            const widget = document.querySelector('[data-has-token], .cf-turnstile, [data-sitekey]');
            const input = document.querySelector('input[name="cf-turnstile-response"]');
            return {
                hasWidget: !!widget,
                tokenAttr: widget ? widget.getAttribute('data-has-token') : null,
                inputLen: input ? input.value.length : 0,
                frameUrls: Array.from(document.querySelectorAll('iframe'))
                    .map((frame) => frame.src || '')
                    .filter(Boolean),
            };
        }""",
        {},
    ) or {}


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


async def _click_login_button(page: Any) -> None:
    last_error: Exception | None = None
    for name in LOGIN_BUTTON_TEXTS:
        try:
            button = page.get_by_role("button", name=name)
            if await button.count() > 0:
                await button.first.click(timeout=10000)
                return
        except Exception as exc:
            last_error = exc
    try:
        await page.locator('button[type="submit"]').last.click(timeout=10000)
        return
    except Exception as exc:
        last_error = exc
    if last_error:
        raise last_error
    raise RuntimeError("login button not found")


def _bool_param(params: dict[str, Any], key: str, default: bool = False) -> bool:
    value = params.get(key)
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _int_param(params: dict[str, Any], key: str, default: int) -> int:
    value = params.get(key)
    if value is None or value == "":
        return default
    return int(value)


def _post_login_url(params: dict[str, Any]) -> str:
    for key in ("post_login_url", "product_url", "concert_url", "ticket_url", "event_url"):
        value = str(params.get(key) or "").strip()
        if value:
            return value
    return ""


async def _dismiss_nol_notices(page: Any) -> dict[str, Any]:
    closed_by_role = 0
    for name in ("关闭", "Close", "닫기", "OK", "확인"):
        try:
            button = page.get_by_role("button", name=name).last
            if await button.count() > 0:
                await button.click(timeout=3000)
                closed_by_role += 1
                await asyncio.sleep(0.5)
        except Exception:
            continue
    closed_by_js = await _safe_eval(
        page,
        """() => {
            let closed = 0;
            const visible = (el) => {
                const r = el.getBoundingClientRect();
                const s = getComputedStyle(el);
                return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
            };
            const selectors = [
                'button.nds-e-modal-bottom-sheet__closeButton',
                'button[aria-label="Close"]',
                'button[aria-label="close"]',
                'button[aria-label="닫기"]',
            ];
            document.querySelectorAll(selectors.join(',')).forEach((button) => {
                if (visible(button)) {
                    button.click();
                    closed += 1;
                }
            });
            if (closed === 0) {
                const buttons = Array.from(document.querySelectorAll('button, [role="button"]'));
                const closeButton = buttons.find((button) => {
                    const text = (button.innerText || button.textContent || '').trim();
                    return visible(button) && ['关闭', 'Close', '닫기', 'OK', '확인'].includes(text);
                });
                if (closeButton) {
                    closeButton.click();
                    closed += 1;
                }
            }
            return closed;
        }""",
        0,
    )
    if int(closed_by_js or 0) > 0:
        await asyncio.sleep(0.5)
    return {"closed_by_role": closed_by_role, "closed_by_js": int(closed_by_js or 0)}


async def _buy_now_state(page: Any) -> dict[str, Any]:
    return await _safe_eval(
        page,
        """(texts) => {
            const visible = (el) => {
                const r = el.getBoundingClientRect();
                const s = getComputedStyle(el);
                return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
            };
            const elements = Array.from(document.querySelectorAll('button, [role="button"], a'));
            const button = elements.find((el) => {
                const text = (el.innerText || el.textContent || el.getAttribute('aria-label') || '').trim();
                return visible(el) && texts.some((item) => text.toLowerCase().includes(item.toLowerCase()));
            });
            if (!button) {
                return {found: false};
            }
            const r = button.getBoundingClientRect();
            return {
                found: true,
                text: (button.innerText || button.textContent || '').trim(),
                disabled: !!button.disabled || button.getAttribute('aria-disabled') === 'true',
                hasSpinner: !!button.querySelector('[role="status"], svg'),
                rect: {x: r.x, y: r.y, width: r.width, height: r.height},
            };
        }""",
        {"found": False},
        list(BUY_BUTTON_TEXTS),
    ) or {"found": False}


async def _click_buy_now(page: Any) -> dict[str, Any]:
    state = await _buy_now_state(page)
    if not state.get("found"):
        return {"clicked": False, "reason": "buy button not found", "state": state}
    if state.get("disabled"):
        return {"clicked": False, "reason": "buy button disabled", "state": state}

    for text in BUY_BUTTON_TEXTS:
        try:
            locator = page.get_by_text(text, exact=False).first
            if await locator.count() > 0:
                await locator.scroll_into_view_if_needed(timeout=5000)
                await locator.click(timeout=10000)
                return {"clicked": True, "method": f"text:{text}", "state": state}
        except Exception:
            continue

    result = await _safe_eval(
        page,
        """(texts) => {
            const visible = (el) => {
                const r = el.getBoundingClientRect();
                const s = getComputedStyle(el);
                return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
            };
            const elements = Array.from(document.querySelectorAll('button, [role="button"], a'));
            const button = elements.find((el) => {
                const text = (el.innerText || el.textContent || el.getAttribute('aria-label') || '').trim();
                return visible(el) && texts.some((item) => text.toLowerCase().includes(item.toLowerCase()));
            });
            if (!button) return {clicked: false, reason: 'buy button not found'};
            if (button.disabled || button.getAttribute('aria-disabled') === 'true') {
                return {clicked: false, reason: 'buy button disabled'};
            }
            button.scrollIntoView({block: 'center'});
            button.click();
            return {clicked: true, method: 'js'};
        }""",
        {"clicked": False, "reason": "js click failed"},
        list(BUY_BUTTON_TEXTS),
    ) or {"clicked": False, "reason": "js click failed"}
    result["state"] = state
    return result


async def _interpark_page(page: Any) -> Any | None:
    pages = [page]
    context = getattr(page, "context", None)
    if context is not None:
        try:
            pages = list(context.pages)
        except Exception:
            pages = [page]
    for candidate in pages:
        try:
            url = candidate.url
        except Exception:
            continue
        if "interpark.com" in url or "globalinterpark.com" in url:
            return candidate
    return None


async def _wait_buy_turnstile_or_redirect(page: Any, timeout_seconds: int) -> tuple[bool, dict[str, Any], Any]:
    start = time.monotonic()
    clicked = False
    last_state: dict[str, Any] = {}
    while time.monotonic() - start < timeout_seconds:
        interpark = await _interpark_page(page)
        if interpark is not None:
            return True, {"redirect": True, "url": interpark.url}, interpark
        state = await _turnstile_state(page)
        last_state = state
        if state.get("tokenAttr") == "true" or int(state.get("inputLen") or 0) > 0:
            return True, state, page
        has_turnstile = bool(state.get("hasWidget")) or any(
            "cloudflare" in str(url).lower() or "turnstile" in str(url).lower()
            for url in state.get("frameUrls") or []
        )
        has_cf_frame = any("challenges.cloudflare.com" in (frame.url or "") for frame in page.frames)
        if (has_turnstile or has_cf_frame) and not clicked and time.monotonic() - start > 2:
            clicked = await _click_turnstile_with_locators(page)
            if clicked:
                await asyncio.sleep(4)
                continue
        if not has_turnstile and not has_cf_frame and time.monotonic() - start > 5:
            return False, last_state, page
        await asyncio.sleep(1)
    return False, last_state, page


async def _wait_interpark_page(page: Any, timeout_seconds: int) -> tuple[bool, Any]:
    start = time.monotonic()
    while time.monotonic() - start < timeout_seconds:
        interpark = await _interpark_page(page)
        if interpark is not None:
            return True, interpark
        await asyncio.sleep(1)
    return False, page


async def _safe_body_text(page: Any, limit: int = 1200) -> str:
    try:
        return (await page.locator("body").inner_text(timeout=5000))[:limit]
    except Exception:
        return ""


async def _run_post_login_flow(page: Any, params: dict[str, Any], timeout_ms: int) -> dict[str, Any] | None:
    product_url = _post_login_url(params)
    if not product_url:
        return None

    buy_attempts = max(1, _int_param(params, "buy_now_attempts", 3))
    buy_turnstile_timeout = max(1, _int_param(params, "buy_turnstile_timeout", 40))
    interpark_timeout = max(1, _int_param(params, "interpark_timeout", 90))
    click_buy = _bool_param(params, "click_buy_now", True)

    result: dict[str, Any] = {
        "product_url": product_url,
        "click_buy_now": click_buy,
        "entered_interpark": False,
        "buy_attempts": 0,
    }

    await page.goto(product_url, wait_until="domcontentloaded", timeout=timeout_ms)
    try:
        await page.wait_for_load_state("networkidle", timeout=min(timeout_ms, 30000))
    except Exception:
        pass
    await asyncio.sleep(2)
    result["notice"] = await _dismiss_nol_notices(page)
    result["product_title"] = await _safe_title(page)
    result["product_url_after_load"] = page.url

    if not click_buy:
        result["buy_button"] = await _buy_now_state(page)
        return result

    last_click: dict[str, Any] = {}
    last_turnstile: dict[str, Any] = {}
    active_page = page
    for attempt in range(1, buy_attempts + 1):
        result["buy_attempts"] = attempt
        await _dismiss_nol_notices(active_page)
        last_click = await _click_buy_now(active_page)
        if not last_click.get("clicked"):
            result["buy_click"] = last_click
            if last_click.get("reason") != "buy button disabled":
                break
            await asyncio.sleep(3)
            continue

        turnstile_ok, turnstile_state, active_page = await _wait_buy_turnstile_or_redirect(
            active_page,
            buy_turnstile_timeout,
        )
        last_turnstile = turnstile_state
        result["buy_turnstile"] = {
            "ok": turnstile_ok,
            "state": turnstile_state,
        }
        interpark = await _interpark_page(active_page)
        if interpark is not None:
            active_page = interpark
            result["entered_interpark"] = True
            break
        if turnstile_ok:
            last_click = await _click_buy_now(active_page)
            result["buy_click_after_turnstile"] = last_click
            if last_click.get("clicked"):
                entered, active_page = await _wait_interpark_page(active_page, interpark_timeout)
                result["entered_interpark"] = entered
                if entered:
                    break

    result["buy_click"] = last_click
    result["last_turnstile_state"] = last_turnstile
    result["final_url"] = active_page.url
    result["final_title"] = await _safe_title(active_page)
    result["final_text"] = await _safe_body_text(active_page)
    return result


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


async def _close_page(page: Any) -> None:
    try:
        await page.close()
    except Exception:
        pass


async def _safe_title(page: Any) -> str:
    try:
        return await page.title()
    except Exception:
        return ""


async def _safe_screenshot(page: Any, path: Any) -> tuple[list[dict[str, str]], str | None]:
    try:
        await page.screenshot(path=str(path), full_page=True)
    except Exception as exc:
        return [], str(exc)
    return [{"type": "screenshot", "uri": str(path)}], None


async def _attempt_login(
    page: Any,
    target_url: str,
    account: str,
    password: str,
    timeout_ms: int,
    turnstile_timeout: int,
) -> tuple[bool, bool, Any]:
    page.set_default_timeout(30000)
    page.set_default_navigation_timeout(timeout_ms)

    await page.goto(target_url, wait_until="domcontentloaded", timeout=timeout_ms)
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
        await _click_login_button(page)
        try:
            await page.wait_for_url("**/my-info**", timeout=25000)
        except Exception:
            try:
                await page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
        await asyncio.sleep(2)

    login_ok = await _verify_login(page, account)
    return turnstile_ok, login_ok, webdriver


async def nol_native_login_v1(ctx: AutomationContext) -> dict[str, Any]:
    account = ctx.account()
    password = str(ctx.params.get("password") or ctx.payload.get("password") or "").strip()
    if not account or not password:
        raise ValueError("nol_native_login_v1 requires account/email and password")

    timeout_ms = max(60000, ctx.timeout_seconds * 1000)
    turnstile_timeout = int(ctx.params.get("auto_turnstile_timeout") or 80)
    page_attempts = max(1, int(ctx.params.get("turnstile_page_attempts") or 2))
    require_login = bool(ctx.params.get("require_login", True))
    page = ctx.page
    target_url = ctx.target_url(NOL_LOGIN_URL)

    turnstile_ok = False
    login_ok = False
    webdriver: Any = "unknown"
    attempt = 0
    for attempt in range(1, page_attempts + 1):
        if attempt > 1:
            await _close_page(page)
            page = await ctx.new_page()
        turnstile_ok, login_ok, webdriver = await _attempt_login(
            page,
            target_url,
            account,
            password,
            timeout_ms,
            turnstile_timeout,
        )
        if turnstile_ok or login_ok:
            break

    login_ok = await _verify_login(page, account)
    post_login_result = None
    if login_ok:
        post_login_result = await _run_post_login_flow(page, ctx.params, timeout_ms)
    screenshot_path = ctx.artifact_path("nol-native-login")
    artifacts, screenshot_error = await _safe_screenshot(page, screenshot_path)
    result = {
        "url": page.url,
        "title": await _safe_title(page),
        "account": account,
        "turnstile": turnstile_ok,
        "login": login_ok,
        "webdriver": webdriver,
        "attempts": attempt,
        "artifacts": artifacts,
    }
    if post_login_result is not None:
        result["post_login"] = post_login_result
    if screenshot_error:
        result["screenshot_error"] = screenshot_error
    if require_login and not (turnstile_ok and login_ok):
        raise AutomationScriptError(
            f"nol native login failed: turnstile={turnstile_ok}, login={login_ok}, url={page.url}",
            result,
        )
    return result
