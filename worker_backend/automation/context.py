from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from worker_backend.browser_manager import RunningProfile


ARTIFACT_DIR = Path("/data/artifacts")


@dataclass
class AutomationContext:
    """Stable surface passed to business scripts.

    Business scripts use Playwright objects from this context, while browser
    lifecycle details stay owned by BrowserManager and the runner.
    """

    running: RunningProfile
    payload: dict[str, Any]
    params: dict[str, Any]
    page: Any
    page_factory: Callable[[], Awaitable[Any]] | None = None
    artifact_dir: Path = ARTIFACT_DIR

    @property
    def timeout_seconds(self) -> int:
        return int(self.params.get("timeout_seconds") or self.payload.get("timeout_seconds") or 300)

    def target_url(self, fallback: str | None = None) -> str:
        value = self.payload.get("target_url") or self.payload.get("url") or self.params.get("target_url") or fallback
        if not value:
            raise ValueError("automation context requires target_url or url")
        return str(value)

    def account(self) -> str:
        return str(self.payload.get("account") or self.params.get("account") or self.params.get("email") or "").strip()

    def artifact_path(self, prefix: str, suffix: str = ".png") -> Path:
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        safe_prefix = prefix.strip().replace("/", "-") or "artifact"
        return self.artifact_dir / f"{safe_prefix}-{self.running.profile_id}-{int(time.time())}{suffix}"

    async def new_page(self) -> Any:
        if self.page_factory:
            return await self.page_factory()
        return await self.running.context.new_page()
