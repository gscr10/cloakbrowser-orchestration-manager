"""Worker API example: create or reuse two profiles and drive them over CDP.

Usage:
  python3 examples/cdp_dual_search.py

Optional environment variables:
  CLOAK_MANAGER_URL=http://127.0.0.1:8080
"""

from __future__ import annotations

import asyncio
import os
from typing import Any
from urllib.parse import quote_plus

import httpx
from playwright.async_api import Browser, Page, async_playwright


MANAGER_URL = os.environ.get("CLOAK_MANAGER_URL", "http://127.0.0.1:8080").rstrip("/")


async def api_request(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    json_body: dict[str, Any] | None = None,
) -> Any:
    response = await client.request(method, path, json=json_body)
    response.raise_for_status()
    if not response.content:
        return None
    return response.json()


async def ensure_profile(client: httpx.AsyncClient, name: str) -> dict[str, Any]:
    profiles = await api_request(client, "GET", "/api/profiles")
    for profile in profiles:
        if profile["name"] == name:
            if profile.get("headless"):
                profile = await api_request(
                    client,
                    "PUT",
                    f"/api/profiles/{profile['id']}",
                    {"headless": False},
                )
            return profile

    return await api_request(
        client,
        "POST",
        "/api/profiles",
        {"name": name, "headless": False},
    )


async def ensure_running(client: httpx.AsyncClient, profile_id: str) -> str:
    status = await api_request(client, "GET", f"/api/profiles/{profile_id}/status")
    if status["status"] != "running":
        await api_request(client, "POST", f"/api/profiles/{profile_id}/launch")

    for _ in range(40):
        status = await api_request(client, "GET", f"/api/profiles/{profile_id}/status")
        cdp_url = status.get("cdp_url")
        if status["status"] == "running" and cdp_url:
            return f"{MANAGER_URL}{cdp_url}"
        await asyncio.sleep(0.5)

    raise RuntimeError(f"profile {profile_id} did not expose CDP in time")


async def ensure_page(browser: Browser) -> Page:
    context = browser.contexts[0] if browser.contexts else await browser.new_context()
    return context.pages[0] if context.pages else await context.new_page()


async def search_baidu(page: Page, keyword: str) -> None:
    await page.goto("https://www.baidu.com", wait_until="domcontentloaded")
    await page.goto(
        f"https://www.baidu.com/s?wd={quote_plus(keyword)}",
        wait_until="domcontentloaded",
    )
    await page.wait_for_timeout(1500)


async def search_bing(page: Page, keyword: str) -> None:
    await page.goto("https://www.bing.com", wait_until="domcontentloaded")
    await page.goto(
        f"https://www.bing.com/search?q={quote_plus(keyword)}",
        wait_until="domcontentloaded",
    )
    await page.wait_for_timeout(1500)


async def drive_profile(
    client: httpx.AsyncClient,
    profile_name: str,
    search_fn,
    keyword: str,
) -> tuple[str, str]:
    profile = await ensure_profile(client, profile_name)
    cdp_endpoint = await ensure_running(client, profile["id"])

    async with async_playwright() as pw:
        browser = await pw.chromium.connect_over_cdp(cdp_endpoint)
        try:
            page = await ensure_page(browser)
            await search_fn(page, keyword)
        finally:
            await browser.close()

    return profile_name, profile["id"]


async def main() -> None:
    async with httpx.AsyncClient(base_url=MANAGER_URL, timeout=30.0) as client:
        results = await asyncio.gather(
            drive_profile(client, "a", search_baidu, "monkeycode"),
            drive_profile(client, "b", search_bing, "bts"),
        )

    for profile_name, profile_id in results:
        print(f"{profile_name}: {profile_id}")


if __name__ == "__main__":
    asyncio.run(main())
