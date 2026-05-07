"""Tests for the independent master HTTP API CLI."""

from __future__ import annotations

import json

from master_backend import cli


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


def test_master_cli_task_get(monkeypatch):
    setup_fake_http(monkeypatch)
    code = cli.main(["task", "task-1"])
    assert code == 0
    assert FakeHttpClient.instances[0].requests == [("GET", "/api/master/tasks/task-1", None)]


def test_master_cli_nodes(monkeypatch):
    setup_fake_http(monkeypatch)
    code = cli.main(["nodes"])
    assert code == 0
    assert FakeHttpClient.instances[0].requests == [("GET", "/api/master/nodes", None)]


def test_master_cli_task_events(monkeypatch):
    setup_fake_http(monkeypatch)
    code = cli.main(["task-events", "task-1"])
    assert code == 0
    assert FakeHttpClient.instances[0].requests == [("GET", "/api/master/tasks/task-1/events", None)]


def test_master_cli_cancel_and_requeue_task(monkeypatch):
    setup_fake_http(monkeypatch)
    assert cli.main(["cancel-task", "task-1"]) == 0
    assert cli.main(["requeue-task", "task-1"]) == 0
    assert FakeHttpClient.instances[0].requests == [("POST", "/api/master/tasks/task-1/cancel", None)]
    assert FakeHttpClient.instances[1].requests == [("POST", "/api/master/tasks/task-1/requeue", None)]


def test_master_cli_sources_and_writeback(monkeypatch):
    setup_fake_http(monkeypatch)
    assert cli.main(["sources"]) == 0
    assert cli.main(["set-writeback-sink", "noop"]) == 0
    assert FakeHttpClient.instances[0].requests == [("GET", "/api/master/sources", None)]
    assert FakeHttpClient.instances[1].requests == [("PUT", "/api/master/writeback/active", {"sink": "noop"})]


def test_master_cli_feishu_provider_commands(monkeypatch):
    setup_fake_http(monkeypatch)
    assert cli.main(["set-provider", "feishu_openapi"]) == 0
    assert cli.main(["validate-feishu"]) == 0
    assert cli.main(["smoke-feishu"]) == 0
    assert FakeHttpClient.instances[0].requests == [("PUT", "/api/master/providers/active", {"provider": "feishu_openapi"})]
    assert FakeHttpClient.instances[1].requests == [("POST", "/api/master/providers/feishu-openapi/validate", None)]
    assert FakeHttpClient.instances[2].requests == [("POST", "/api/master/providers/feishu-openapi/smoke", None)]


def test_master_cli_provision_job_get(monkeypatch):
    setup_fake_http(monkeypatch)
    code = cli.main(["provision-job", "job-1"])
    assert code == 0
    assert FakeHttpClient.instances[0].requests == [("GET", "/api/master/provision/jobs/job-1", None)]
