from __future__ import annotations

from types import SimpleNamespace

import pytest

from worker_backend.automation import (
    AutomationScriptError,
    list_templates,
    register_template,
    run_template,
    unregister_template,
)


class FakeBrowserContext:
    def __init__(self) -> None:
        self.pages = []

    async def new_page(self):
        page = SimpleNamespace(name="fresh-page")
        self.pages.append(page)
        return page


@pytest.mark.asyncio
async def test_custom_automation_template_receives_stable_context():
    async def echo_handler(ctx):
        return {
            "page": ctx.page.name,
            "target_url": ctx.target_url(),
            "account": ctx.account(),
            "timeout_seconds": ctx.timeout_seconds,
        }

    try:
        register_template("unit_test_echo", "v1", echo_handler)
        running = SimpleNamespace(
            profile_id="profile-1",
            context=FakeBrowserContext(),
            cdp_port=5100,
        )

        result = await run_template(
            running,
            {
                "script_key": "unit_test_echo",
                "script_version": "v1",
                "url": "https://example.test",
                "account": "user@example.test",
                "timeout_seconds": 123,
                "biz_params": {"use_cdp_automation": False},
            },
        )
    finally:
        unregister_template("unit_test_echo", "v1")

    assert result == {
        "script_key": "unit_test_echo",
        "script_version": "v1",
        "result": {
            "page": "fresh-page",
            "target_url": "https://example.test",
            "account": "user@example.test",
            "timeout_seconds": 123,
        },
    }


@pytest.mark.asyncio
async def test_script_error_result_is_wrapped_like_success_result():
    async def fail_handler(ctx):
        raise AutomationScriptError(
            "script failed",
            {"turnstile": False, "artifacts": [{"type": "screenshot", "uri": "/tmp/a.png"}]},
        )

    try:
        register_template("unit_test_fail", "v1", fail_handler)
        running = SimpleNamespace(
            profile_id="profile-1",
            context=FakeBrowserContext(),
            cdp_port=5100,
        )

        with pytest.raises(AutomationScriptError) as exc_info:
            await run_template(
                running,
                {
                    "script_key": "unit_test_fail",
                    "script_version": "v1",
                    "url": "https://example.test",
                    "biz_params": {"use_cdp_automation": False},
                },
            )
    finally:
        unregister_template("unit_test_fail", "v1")

    assert exc_info.value.result == {
        "script_key": "unit_test_fail",
        "script_version": "v1",
        "result": {
            "turnstile": False,
            "artifacts": [{"type": "screenshot", "uri": "/tmp/a.png"}],
        },
    }


def test_builtin_automation_templates_are_listed():
    templates = list_templates()
    assert {"script_key": "open_url", "script_version": "v1", "input_schema_version": "v1"} in templates
    assert {"script_key": "itp_login_ticket", "script_version": "v1", "input_schema_version": "v1"} in templates
    assert {"script_key": "nol_native_login", "script_version": "v1", "input_schema_version": "v1"} in templates
