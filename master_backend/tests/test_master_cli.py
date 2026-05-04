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


def test_master_cli_provision_job_get(monkeypatch):
    setup_fake_http(monkeypatch)
    code = cli.main(["provision-job", "job-1"])
    assert code == 0
    assert FakeHttpClient.instances[0].requests == [("GET", "/api/master/provision/jobs/job-1", None)]
