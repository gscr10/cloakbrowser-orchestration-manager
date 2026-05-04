"""Tests for the HTTP API CLI."""

from __future__ import annotations

import json

from worker_backend import cli


class FakeResponse:
    def __init__(self, status_code: int = 200, data: object | None = None) -> None:
        self.status_code = status_code
        self._data = data if data is not None else {"ok": True}
        self.content = b"{}"
        self.text = json.dumps(self._data)

    def json(self) -> object:
        return self._data


class FakeHttpClient:
    instances: list["FakeHttpClient"] = []
    next_response = FakeResponse()

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.requests: list[tuple[str, str, object | None]] = []
        self.closed = False
        FakeHttpClient.instances.append(self)

    def request(self, method: str, path: str, json: object | None = None) -> FakeResponse:
        self.requests.append((method, path, json))
        return FakeHttpClient.next_response

    def close(self) -> None:
        self.closed = True


def setup_fake_http(monkeypatch):
    FakeHttpClient.instances = []
    FakeHttpClient.next_response = FakeResponse(data={"ok": True})
    monkeypatch.setattr(cli.httpx, "Client", FakeHttpClient)


def test_cli_passes_base_url_and_token(monkeypatch, capsys):
    setup_fake_http(monkeypatch)
    FakeHttpClient.next_response = FakeResponse(data={"running_count": 0})

    code = cli.main([
        "--base-url", "http://manager.test",
        "--token", "secret",
        "status",
    ])

    assert code == 0
    client = FakeHttpClient.instances[0]
    assert client.kwargs["base_url"] == "http://manager.test"
    assert client.kwargs["headers"] == {"Authorization": "Bearer secret"}
    assert client.requests == [("GET", "/api/status", None)]
    assert json.loads(capsys.readouterr().out) == {"running_count": 0}


def test_cli_creates_profile(monkeypatch):
    setup_fake_http(monkeypatch)

    code = cli.main([
        "profiles", "create", "worker-1",
        "--proxy", "http://user:pass@proxy.test:8080",
        "--platform", "linux",
        "--screen-width", "1280",
        "--screen-height", "720",
        "--headless",
        "--tag", "automation",
    ])

    assert code == 0
    method, path, body = FakeHttpClient.instances[0].requests[0]
    assert method == "POST"
    assert path == "/api/profiles"
    assert body == {
        "name": "worker-1",
        "proxy": "http://user:pass@proxy.test:8080",
        "platform": "linux",
        "screen_width": 1280,
        "screen_height": 720,
        "headless": True,
        "tags": [{"tag": "automation"}],
    }


def test_cli_imports_proxy_csv(monkeypatch, tmp_path):
    setup_fake_http(monkeypatch)
    csv_path = tmp_path / "proxies.csv"
    csv_path.write_text("protocol,host,port\nhttp,proxy.test,8080\n", encoding="utf-8")

    code = cli.main(["proxies", "import", str(csv_path)])


    assert code == 0
    method, path, body = FakeHttpClient.instances[0].requests[0]
    assert method == "POST"
    assert path == "/api/proxies/import"
    assert body == {"csv": "protocol,host,port\nhttp,proxy.test,8080\n"}


def test_cli_returns_nonzero_on_api_error(monkeypatch, capsys):
    setup_fake_http(monkeypatch)
    FakeHttpClient.next_response = FakeResponse(status_code=404, data={"detail": "Profile not found"})

    code = cli.main(["profiles", "get", "missing"])

    assert code == 1
    assert "API error 404" in capsys.readouterr().err


def test_cli_uses_environment_defaults(monkeypatch):
    setup_fake_http(monkeypatch)
    monkeypatch.setenv("CLOAK_MANAGER_URL", "http://env-manager.test")
    monkeypatch.setenv("CLOAK_MANAGER_TOKEN", "env-secret")

    code = cli.main(["tasks", "list"])

    assert code == 0
    client = FakeHttpClient.instances[0]
    assert client.kwargs["base_url"] == "http://env-manager.test"
    assert client.kwargs["headers"] == {"Authorization": "Bearer env-secret"}
    assert client.requests == [("GET", "/api/tasks", None)]


def test_cli_imports_external_config(monkeypatch):
    setup_fake_http(monkeypatch)

    code = cli.main(["config", "import"])

    assert code == 0
    assert FakeHttpClient.instances[0].requests == [("POST", "/api/config/import", None)]


def test_cli_allows_open_url_without_url(monkeypatch):
    setup_fake_http(monkeypatch)

    code = cli.main([
        "tasks", "create",
        "--profile-id", "profile-1",
        "--authorized-target", "internal test app",
        "--task-type", "open_url",
    ])

    assert code == 0
    assert FakeHttpClient.instances[0].requests == [
        (
            "POST",
            "/api/tasks",
            {
                "profile_id": "profile-1",
                "authorized_target": "internal test app",
                "task_type": "open_url",
                "url": None,
                "timeout_seconds": 300,
            },
        )
    ]


def test_cli_accepts_compact_after_subcommand(monkeypatch, capsys):
    setup_fake_http(monkeypatch)
    FakeHttpClient.next_response = FakeResponse(data={"ok": True})

    code = cli.main(["status", "--compact"])

    assert code == 0
    assert capsys.readouterr().out == '{"ok": true}\n'

