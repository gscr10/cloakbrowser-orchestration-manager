from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from starlette.testclient import TestClient

from master_backend import biz_sync, infra_sync, master_control


def test_master_node_register_and_heartbeat(master_app_client: TestClient):
    register = master_app_client.post(
        "/api/master/nodes/register",
        json={
            "node_id": "worker-a",
            "hostname": "worker-a.local",
            "max_profiles": 10,
            "tags": ["cn"],
        },
    )
    assert register.status_code == 200
    assert register.json()["node"]["node_id"] == "worker-a"

    heartbeat = master_app_client.post(
        "/api/master/nodes/heartbeat",
        json={
            "node_id": "worker-a",
            "running_profiles": 2,
            "cpu_percent": 11.5,
            "mem_total_mb": 8192,
            "mem_used_mb": 4096,
            "status": "online",
        },
    )
    assert heartbeat.status_code == 200
    assert heartbeat.json()["node"]["running_profiles"] == 2


def test_master_nodes_list_endpoint(master_app_client: TestClient):
    master_app_client.post(
        "/api/master/nodes/register",
        json={
            "node_id": "worker-a",
            "hostname": "worker-a.local",
            "max_profiles": 10,
            "tags": ["cn"],
        },
    )
    listed = master_app_client.get("/api/master/nodes")
    assert listed.status_code == 200
    payload = listed.json()
    assert len(payload) >= 1
    assert payload[0]["node_id"] == "worker-a"


def test_master_register_stores_worker_capabilities(master_app_client: TestClient):
    register = master_app_client.post(
        "/api/master/nodes/register",
        json={
            "node_id": "worker-a",
            "hostname": "worker-a.local",
            "max_profiles": 10,
            "capabilities": [{"script_key": "open_url", "script_version": "v1"}],
        },
    )
    assert register.status_code == 200

    caps = master_app_client.get("/api/master/infra/capabilities")
    assert caps.status_code == 200
    assert caps.json() == [
        {
            "node_id": "worker-a",
            "script_key": "open_url",
            "script_version": "v1",
            "input_schema_version": "v1",
            "updated_at": caps.json()[0]["updated_at"],
        }
    ]


def test_master_local_json_infra_sync(master_app_client: TestClient, tmp_path: Path, monkeypatch):
    workers_path = tmp_path / "infra_workers.json"
    workers_path.write_text(
        json.dumps(
            {
                "workers": [
                    {
                        "node_id": "worker-json",
                        "host": "10.0.0.20",
                        "ssh_user": "root",
                        "ssh_port": 2222,
                        "desired_state": "active",
                        "tags": ["kr", "ticket"],
                        "worker_api_base": "http://10.0.0.20:8080",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(infra_sync, "INFRA_WORKERS_PATH", workers_path)

    sync = master_app_client.post("/api/master/infra/sync")
    assert sync.status_code == 200
    assert sync.json()["count"] == 1

    workers = master_app_client.get("/api/master/infra/workers")
    assert workers.status_code == 200
    assert workers.json()[0]["node_id"] == "worker-json"
    assert workers.json()[0]["tags"] == ["kr", "ticket"]


def test_master_local_json_biz_sync_and_schedule(master_app_client: TestClient, tmp_path: Path, monkeypatch):
    workers_path = tmp_path / "infra_workers.json"
    workers_path.write_text(
        json.dumps(
            {
                "workers": [
                    {
                        "node_id": "worker-a",
                        "host": "10.0.0.10",
                        "tags": ["kr", "ticket"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    jobs_path = tmp_path / "biz_tasks.json"
    jobs_path.write_text(
        json.dumps(
            {
                "jobs": [
                    {
                        "job_key": "ticket-1",
                        "source_record_id": "rec-1",
                        "run_generation": 2,
                        "script_key": "open_url",
                        "script_version": "v1",
                        "target_url": "https://example.com",
                        "worker_tags": ["kr", "ticket"],
                        "params": {"account": "demo"},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(infra_sync, "INFRA_WORKERS_PATH", workers_path)
    monkeypatch.setattr(biz_sync, "BIZ_TASKS_PATH", jobs_path)
    assert master_app_client.post("/api/master/infra/sync").status_code == 200
    master_app_client.post(
        "/api/master/nodes/register",
        json={
            "node_id": "worker-a",
            "hostname": "worker-a.local",
            "max_profiles": 10,
            "capabilities": [{"script_key": "open_url", "script_version": "v1"}],
        },
    )

    sync = master_app_client.post("/api/master/biz/sync", json={"schedule": True})
    assert sync.status_code == 200
    data = sync.json()
    assert data["count"] == 1
    assert data["jobs"][0]["idempotency_key"] == "rec-1:2"
    assert data["scheduled"][0]["assigned_worker"] == "worker-a"

    tasks = master_app_client.get("/api/master/tasks").json()
    task = tasks[0]
    assert task["task_type"] == "automation_script"
    assert task["payload"]["script_key"] == "open_url"
    assert task["target_node_id"] == "worker-a"


def test_master_biz_schedule_waits_when_infra_worker_disabled(master_app_client: TestClient, tmp_path: Path, monkeypatch):
    workers_path = tmp_path / "infra_workers.json"
    workers_path.write_text(
        json.dumps(
            {
                "workers": [
                    {
                        "node_id": "worker-a",
                        "host": "10.0.0.10",
                        "enabled": False,
                        "desired_state": "disabled",
                        "tags": ["kr", "ticket"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    jobs_path = tmp_path / "biz_tasks.json"
    jobs_path.write_text(
        json.dumps(
            {
                "jobs": [
                    {
                        "job_key": "ticket-1",
                        "source_record_id": "rec-disabled",
                        "run_generation": 1,
                        "script_key": "open_url",
                        "script_version": "v1",
                        "target_url": "https://example.com",
                        "worker_tags": ["kr", "ticket"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(infra_sync, "INFRA_WORKERS_PATH", workers_path)
    monkeypatch.setattr(biz_sync, "BIZ_TASKS_PATH", jobs_path)
    assert master_app_client.post("/api/master/infra/sync").status_code == 200
    master_app_client.post(
        "/api/master/nodes/register",
        json={
            "node_id": "worker-a",
            "hostname": "worker-a.local",
            "max_profiles": 10,
            "capabilities": [{"script_key": "open_url", "script_version": "v1"}],
        },
    )

    sync = master_app_client.post("/api/master/biz/sync", json={"schedule": True})
    assert sync.status_code == 200
    scheduled = sync.json()["scheduled"][0]
    assert scheduled["status"] == "pending_schedule"
    assert scheduled["assigned_worker"] is None
    assert scheduled["master_task_id"] is None

    assert master_app_client.get("/api/master/tasks").json() == []


def test_master_profile_auto_selection_skips_running_profiles(monkeypatch):
    class FakeResponse:
        def __init__(self, body):
            self._body = body

        def raise_for_status(self):
            return None

        def json(self):
            return self._body

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def get(self, path):
            return FakeResponse(
                [
                    {"id": "running-profile", "name": "ticket-profile", "status": "running"},
                    {"id": "ready-profile", "name": "ticket-profile", "status": "ready"},
                    {"id": "other-profile", "name": "other", "status": "stopped"},
                ]
            )

    monkeypatch.setattr(master_control.httpx, "Client", FakeClient)

    node = {"api_base": "http://worker-a:8080", "token": None}
    assert master_control._fetch_worker_profile_id(node, preferred_name="ticket-profile") == "ready-profile"
    assert master_control._fetch_worker_profile_id(node, preferred_name="missing") is None
    assert master_control._fetch_worker_profile_id(node) == "ready-profile"


def test_master_create_pull_report_task(master_app_client: TestClient):
    master_app_client.post(
        "/api/master/nodes/register",
        json={"node_id": "worker-a", "hostname": "worker-a.local", "max_profiles": 10},
    )
    master_app_client.post(
        "/api/master/nodes/register",
        json={"node_id": "worker-b", "hostname": "worker-b.local", "max_profiles": 10},
    )
    master_app_client.post(
        "/api/master/nodes/heartbeat",
        json={"node_id": "worker-a", "running_profiles": 6, "status": "online"},
    )
    master_app_client.post(
        "/api/master/nodes/heartbeat",
        json={"node_id": "worker-b", "running_profiles": 1, "status": "online"},
    )

    created = master_app_client.post(
        "/api/master/tasks",
        json={
            "profile_id": "p1",
            "authorized_target": "internal test app",
            "task_type": "open_url",
        },
    )
    assert created.status_code == 201
    task = created.json()
    assert task["target_node_id"] == "worker-b"
    assert task["payload"]["url"] == "https://www.baidu.com"

    pulled = master_app_client.post("/api/master/tasks/pull", json={"node_id": "worker-b"})
    assert pulled.status_code == 200
    pulled_task = pulled.json()["task"]
    assert pulled_task["id"] == task["id"]
    assert pulled_task["status"] == "dispatched"

    started = master_app_client.post(
        f"/api/master/tasks/{task['id']}/report",
        json={"node_id": "worker-b", "status": "started"},
    )
    assert started.status_code == 200
    assert started.json()["status"] == "running"

    success = master_app_client.post(
        f"/api/master/tasks/{task['id']}/report",
        json={"node_id": "worker-b", "status": "success", "dispatch_id": pulled_task["dispatch_id"]},
    )
    assert success.status_code == 200
    assert success.json()["status"] == "success"


def test_master_report_dispatch_mismatch(master_app_client: TestClient):
    master_app_client.post(
        "/api/master/nodes/register",
        json={"node_id": "worker-a", "hostname": "worker-a.local", "max_profiles": 10},
    )
    master_app_client.post(
        "/api/master/nodes/heartbeat",
        json={"node_id": "worker-a", "running_profiles": 0, "status": "online"},
    )
    created = master_app_client.post(
        "/api/master/tasks",
        json={"profile_id": "p1", "authorized_target": "internal test app", "task_type": "external_cdp"},
    )
    task = created.json()
    pulled = master_app_client.post("/api/master/tasks/pull", json={"node_id": "worker-a"}).json()["task"]
    assert pulled["id"] == task["id"]

    bad = master_app_client.post(
        f"/api/master/tasks/{task['id']}/report",
        json={"node_id": "worker-a", "status": "success", "dispatch_id": "wrong-id"},
    )
    assert bad.status_code == 409


def test_master_pull_claims_unassigned_task(master_app_client: TestClient):
    master_app_client.post(
        "/api/master/nodes/register",
        json={"node_id": "worker-a", "hostname": "worker-a.local", "max_profiles": 10},
    )
    master_app_client.post(
        "/api/master/nodes/heartbeat",
        json={"node_id": "worker-a", "running_profiles": 0, "status": "online"},
    )

    from master_backend import master_control as mc
    original = mc.pick_target_node
    try:
        mc.pick_target_node = lambda: None  # type: ignore[assignment]
        created = master_app_client.post(
            "/api/master/tasks",
            json={"profile_id": "p1", "authorized_target": "internal test app", "task_type": "external_cdp"},
        )
    finally:
        mc.pick_target_node = original  # type: ignore[assignment]

    task = created.json()
    assert task["target_node_id"] is None

    pulled = master_app_client.post("/api/master/tasks/pull", json={"node_id": "worker-a"})
    assert pulled.status_code == 200
    pulled_task = pulled.json()["task"]
    assert pulled_task["id"] == task["id"]
    assert pulled_task["target_node_id"] == "worker-a"


def test_master_get_task_endpoint(master_app_client: TestClient):
    master_app_client.post(
        "/api/master/nodes/register",
        json={"node_id": "worker-a", "hostname": "worker-a.local", "max_profiles": 10},
    )
    master_app_client.post(
        "/api/master/nodes/heartbeat",
        json={"node_id": "worker-a", "running_profiles": 0, "status": "online"},
    )
    created = master_app_client.post(
        "/api/master/tasks",
        json={"profile_id": "p1", "authorized_target": "internal test app", "task_type": "external_cdp"},
    ).json()
    got = master_app_client.get(f"/api/master/tasks/{created['id']}")
    assert got.status_code == 200
    assert got.json()["id"] == created["id"]


def test_master_get_task_events_endpoint(master_app_client: TestClient):
    master_app_client.post(
        "/api/master/nodes/register",
        json={"node_id": "worker-a", "hostname": "worker-a.local", "max_profiles": 10},
    )
    master_app_client.post(
        "/api/master/nodes/heartbeat",
        json={"node_id": "worker-a", "running_profiles": 0, "status": "online"},
    )
    created = master_app_client.post(
        "/api/master/tasks",
        json={"profile_id": "p1", "authorized_target": "internal test app", "task_type": "external_cdp"},
    ).json()
    master_app_client.post("/api/master/tasks/pull", json={"node_id": "worker-a"})

    events = master_app_client.get(f"/api/master/tasks/{created['id']}/events")
    assert events.status_code == 200
    payload = events.json()
    assert len(payload) >= 1
    assert payload[0]["task_id"] == created["id"]


def test_master_failed_task_is_requeued_with_retry(master_app_client: TestClient):
    master_app_client.post(
        "/api/master/nodes/register",
        json={"node_id": "worker-a", "hostname": "worker-a.local", "max_profiles": 10},
    )
    master_app_client.post(
        "/api/master/nodes/heartbeat",
        json={"node_id": "worker-a", "running_profiles": 0, "status": "online"},
    )
    created = master_app_client.post(
        "/api/master/tasks",
        json={"profile_id": "p1", "authorized_target": "internal test app", "task_type": "external_cdp", "max_retries": 2},
    )
    task = created.json()
    pulled = master_app_client.post("/api/master/tasks/pull", json={"node_id": "worker-a"}).json()["task"]
    failed = master_app_client.post(
        f"/api/master/tasks/{task['id']}/report",
        json={"node_id": "worker-a", "status": "failed", "dispatch_id": pulled["dispatch_id"], "failure_reason": "boom"},
    )
    assert failed.status_code == 200
    data = failed.json()
    assert data["status"] == "queued"
    assert data["retry_count"] == 1


def test_master_external_cdp_auto_fills_profile_id_on_pull(master_app_client: TestClient, monkeypatch):
    master_app_client.post(
        "/api/master/nodes/register",
        json={
            "node_id": "worker-a",
            "hostname": "worker-a.local",
            "api_base": "http://127.0.0.1:8081",
            "max_profiles": 10,
        },
    )
    master_app_client.post(
        "/api/master/nodes/heartbeat",
        json={"node_id": "worker-a", "running_profiles": 0, "status": "online"},
    )
    monkeypatch.setattr(master_control, "_fetch_worker_profile_id", lambda node, **kwargs: "auto-p1")

    created = master_app_client.post(
        "/api/master/tasks",
        json={"authorized_target": "internal test app", "task_type": "external_cdp"},
    )
    assert created.status_code == 201
    task = created.json()
    assert task["profile_id"] is None

    pulled = master_app_client.post("/api/master/tasks/pull", json={"node_id": "worker-a"})
    assert pulled.status_code == 200
    pulled_task = pulled.json()["task"]
    assert pulled_task["id"] == task["id"]
    assert pulled_task["profile_id"] == "auto-p1"
    assert pulled_task["payload"]["profile_id"] == "auto-p1"


def test_master_external_cdp_keeps_empty_profile_id_when_worker_has_none(master_app_client: TestClient, monkeypatch):
    master_app_client.post(
        "/api/master/nodes/register",
        json={
            "node_id": "worker-a",
            "hostname": "worker-a.local",
            "api_base": "http://127.0.0.1:8081",
            "max_profiles": 10,
        },
    )
    master_app_client.post(
        "/api/master/nodes/heartbeat",
        json={"node_id": "worker-a", "running_profiles": 0, "status": "online"},
    )
    monkeypatch.setattr(master_control, "_fetch_worker_profile_id", lambda node, **kwargs: None)

    created = master_app_client.post(
        "/api/master/tasks",
        json={"authorized_target": "internal test app", "task_type": "external_cdp"},
    )
    assert created.status_code == 201
    task = created.json()

    pulled = master_app_client.post("/api/master/tasks/pull", json={"node_id": "worker-a"})
    assert pulled.status_code == 200
    pulled_task = pulled.json()["task"]
    assert pulled_task["id"] == task["id"]
    assert pulled_task["profile_id"] is None
    assert pulled_task["payload"].get("profile_id") is None


def test_master_open_url_auto_fills_profile_id_on_pull(master_app_client: TestClient, monkeypatch):
    master_app_client.post(
        "/api/master/nodes/register",
        json={
            "node_id": "worker-a",
            "hostname": "worker-a.local",
            "api_base": "http://127.0.0.1:8081",
            "max_profiles": 10,
        },
    )
    master_app_client.post(
        "/api/master/nodes/heartbeat",
        json={"node_id": "worker-a", "running_profiles": 0, "status": "online"},
    )
    monkeypatch.setattr(master_control, "_fetch_worker_profile_id", lambda node, **kwargs: "auto-open-url-p1")

    created = master_app_client.post(
        "/api/master/tasks",
        json={"authorized_target": "internal test app", "task_type": "open_url", "url": "https://www.baidu.com"},
    )
    assert created.status_code == 201
    task = created.json()
    assert task["profile_id"] is None

    pulled = master_app_client.post("/api/master/tasks/pull", json={"node_id": "worker-a"})
    assert pulled.status_code == 200
    pulled_task = pulled.json()["task"]
    assert pulled_task["id"] == task["id"]
    assert pulled_task["profile_id"] == "auto-open-url-p1"
    assert pulled_task["payload"]["profile_id"] == "auto-open-url-p1"


def test_master_open_url_auto_creates_profile_when_worker_has_none(master_app_client: TestClient, monkeypatch):
    master_app_client.post(
        "/api/master/nodes/register",
        json={
            "node_id": "worker-a",
            "hostname": "worker-a.local",
            "api_base": "http://127.0.0.1:8081",
            "max_profiles": 10,
        },
    )
    master_app_client.post(
        "/api/master/nodes/heartbeat",
        json={"node_id": "worker-a", "running_profiles": 0, "status": "online"},
    )
    monkeypatch.setattr(master_control, "_fetch_worker_profile_id", lambda node, **kwargs: None)
    monkeypatch.setattr(master_control, "_create_worker_profile", lambda node, **kwargs: "auto-created-open-url-p1")

    created = master_app_client.post(
        "/api/master/tasks",
        json={"authorized_target": "internal test app", "task_type": "open_url", "url": "https://www.baidu.com"},
    )
    assert created.status_code == 201
    task = created.json()

    pulled = master_app_client.post("/api/master/tasks/pull", json={"node_id": "worker-a"})
    assert pulled.status_code == 200
    pulled_task = pulled.json()["task"]
    assert pulled_task["id"] == task["id"]
    assert pulled_task["profile_id"] == "auto-created-open-url-p1"
    assert pulled_task["payload"]["profile_id"] == "auto-created-open-url-p1"


def test_master_cluster_marks_stale_nodes(master_app_client: TestClient, monkeypatch):
    master_app_client.post(
        "/api/master/nodes/register",
        json={"node_id": "worker-a", "hostname": "worker-a.local", "max_profiles": 10},
    )

    from master_backend import database as db
    with db.get_db() as conn:
        conn.execute("UPDATE master_nodes SET last_heartbeat_at = ? WHERE node_id = ?", ("2000-01-01T00:00:00+00:00", "worker-a"))
        conn.commit()

    monkeypatch.setattr(master_control, "NODE_HEARTBEAT_TTL_SECONDS", 1)
    status = master_app_client.get("/api/master/cluster/status")
    assert status.status_code == 200
    nodes = status.json()["nodes"]
    assert nodes[0]["status"] == "stale"


def test_master_provider_and_provision_dry_run(master_app_client: TestClient, tmp_path: Path, monkeypatch):
    server_list = tmp_path / "servers.json"
    server_list.write_text(
        json.dumps(
            {
                "servers": [
                    {
                        "node_id": "worker-a",
                        "host": "10.0.0.10",
                        "username": "root",
                        "max_profiles": 10,
                        "enabled": True,
                    },
                    {
                        "node_id": "worker-b",
                        "host": "10.0.0.11",
                        "username": "root",
                        "max_profiles": 10,
                        "enabled": True,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(master_control, "SERVER_LIST_PATH", server_list)

    providers = master_app_client.get("/api/master/providers")
    assert providers.status_code == 200
    assert "static" in providers.json()["providers"]

    set_provider = master_app_client.put("/api/master/providers/active", json={"provider": "static"})
    assert set_provider.status_code == 200
    assert set_provider.json()["active"] == "static"

    reserved_provider = master_app_client.put("/api/master/providers/active", json={"provider": "feishu_cli"})
    assert reserved_provider.status_code == 422
    assert "not implemented yet" in reserved_provider.json()["detail"]

    provision = master_app_client.post("/api/master/provision/run", json={"dry_run": True})
    assert provision.status_code == 200
    data = provision.json()
    assert data["job"]["status"] == "success"
    assert len(data["items"]) == 2

    list_jobs = master_app_client.get("/api/master/provision/jobs")
    assert list_jobs.status_code == 200
    assert len(list_jobs.json()) >= 1


def test_master_provision_endpoint_runs_in_threadpool(master_app_client: TestClient, monkeypatch):
    from master_backend import main as master_main

    captured: dict[str, object] = {}

    async def fake_run_in_threadpool(func, *args, **kwargs):
        captured["func"] = func
        captured["kwargs"] = kwargs
        return {"job": {"status": "success"}, "items": []}

    monkeypatch.setattr(master_main, "run_in_threadpool", fake_run_in_threadpool)

    resp = master_app_client.post("/api/master/provision/run", json={"dry_run": False})
    assert resp.status_code == 200
    assert captured["func"] is master_control.run_provision
    assert captured["kwargs"] == {"dry_run": False}


def test_master_provision_servers_endpoint(master_app_client: TestClient, tmp_path: Path, monkeypatch):
    server_list = tmp_path / "servers.json"
    server_list.write_text(
        json.dumps(
            {
                "servers": [
                    {
                        "node_id": "worker-a",
                        "host": "10.0.0.10",
                        "username": "root",
                        "port": 2222,
                        "max_profiles": 10,
                        "enabled": True,
                        "tags": ["cn"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(master_control, "SERVER_LIST_PATH", server_list)

    master_app_client.put("/api/master/providers/active", json={"provider": "static"})
    resp = master_app_client.get("/api/master/provision/servers")
    assert resp.status_code == 200
    data = resp.json()
    assert data["provider"] == "static"
    assert len(data["servers"]) == 1
    assert data["servers"][0]["node_id"] == "worker-a"
    assert data["servers"][0]["port"] == 2222


def test_master_provision_non_dry_run_uses_command_templates(master_app_client: TestClient, tmp_path: Path, monkeypatch):
    server_list = tmp_path / "servers.json"
    server_list.write_text(
        json.dumps(
            {
                "servers": [
                    {
                        "node_id": "worker-a",
                        "host": "10.0.0.10",
                        "username": "root",
                        "max_profiles": 9,
                        "enabled": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(master_control, "SERVER_LIST_PATH", server_list)
    monkeypatch.setattr(master_control, "PROVISION_CONFIG_PATH", tmp_path / "missing-provision.json")
    monkeypatch.setattr(master_control, "PROVISION_BOOTSTRAP_CMD", "echo boot {node_id} {max_profiles}")
    monkeypatch.setattr(master_control, "PROVISION_MASTER_BASE_URL", "http://master.test:8080")
    monkeypatch.setattr(master_control, "PROVISION_START_CMD", "echo start {host} {master_base_url}")

    captured: dict[str, object] = {}

    def fake_run(cmd, capture_output, text, check, timeout, env=None):
        captured["cmd"] = cmd
        captured["timeout"] = timeout
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(master_control.subprocess, "run", fake_run)
    monkeypatch.setattr(
        master_control,
        "verify_node_registered",
        lambda node_id, min_heartbeat_after, wait_seconds, interval_seconds: (True, "verified"),
    )

    set_provider = master_app_client.put("/api/master/providers/active", json={"provider": "static"})
    assert set_provider.status_code == 200

    provision = master_app_client.post("/api/master/provision/run", json={"dry_run": False})
    assert provision.status_code == 200
    data = provision.json()
    assert data["job"]["status"] == "success"
    assert data["items"][0]["status"] == "success"

    cmd = captured["cmd"]
    assert isinstance(cmd, list)
    assert "root@10.0.0.10" in cmd
    assert "echo boot worker-a 9; echo start 10.0.0.10 http://master.test:8080" in cmd


def test_master_provision_default_start_command_sets_public_worker_api(master_app_client: TestClient, tmp_path: Path, monkeypatch):
    server_list = tmp_path / "servers.json"
    server_list.write_text(
        json.dumps(
            {
                "servers": [
                    {
                        "node_id": "worker-public",
                        "host": "203.0.113.10",
                        "username": "ec2-user",
                        "max_profiles": 2,
                        "enabled": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(master_control, "SERVER_LIST_PATH", server_list)
    monkeypatch.setattr(master_control, "PROVISION_CONFIG_PATH", tmp_path / "missing-provision.json")
    monkeypatch.setattr(master_control, "PROVISION_MASTER_BASE_URL", "http://198.51.100.20:8080")
    monkeypatch.setattr(master_control, "PROVISION_WORKER_API_BASE", "http://{host}:8080")

    captured: dict[str, object] = {}

    def fake_run(cmd, capture_output, text, check, timeout, env=None):
        captured["cmd"] = cmd
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(master_control.subprocess, "run", fake_run)
    monkeypatch.setattr(master_control, "verify_node_registered", lambda *args, **kwargs: (True, "verified"))

    master_app_client.put("/api/master/providers/active", json={"provider": "static"})
    provision = master_app_client.post("/api/master/provision/run", json={"dry_run": False})
    assert provision.status_code == 200

    cmd = captured["cmd"]
    assert isinstance(cmd, list)
    remote_cmd = cmd[-1]
    assert (
        'DOCKER="docker"; docker ps >/dev/null 2>&1 || DOCKER="sudo -n docker"; '
        "$DOCKER --version >/dev/null 2>&1"
    ) in remote_cmd
    assert "$DOCKER pull ghcr.io/gscr10/cloakbrowser-orchestration-manager-worker:latest" in remote_cmd
    assert "$DOCKER rm -f cloak-manager-worker" in remote_cmd
    assert "$DOCKER run -d --name cloak-manager-worker" in remote_cmd
    assert "docker run -d --name cloak-manager-worker" not in remote_cmd
    assert "--shm-size=512m" in remote_cmd
    assert "-e MASTER_BASE_URL=http://198.51.100.20:8080" in remote_cmd
    assert "-e WORKER_API_BASE=http://203.0.113.10:8080" in remote_cmd
    assert "MAX_RUNNING_PROFILES" not in remote_cmd


def test_master_provision_uses_config_file(master_app_client: TestClient, tmp_path: Path, monkeypatch):
    server_list = tmp_path / "servers.json"
    server_list.write_text(
        json.dumps(
            {
                "servers": [
                    {
                        "node_id": "worker-c",
                        "host": "10.0.0.12",
                        "username": "root",
                        "max_profiles": 7,
                        "enabled": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    provision_cfg = tmp_path / "provision.json"
    provision_cfg.write_text(
        json.dumps(
            {
                "timeout_seconds": 55,
                "bootstrap_cmd": "echo cfg-boot {node_id}",
                "start_cmd": "echo cfg-start {max_profiles}",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(master_control, "SERVER_LIST_PATH", server_list)
    monkeypatch.setattr(master_control, "PROVISION_CONFIG_PATH", provision_cfg)

    captured: dict[str, object] = {}

    def fake_run(cmd, capture_output, text, check, timeout, env=None):
        captured["cmd"] = cmd
        captured["timeout"] = timeout
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(master_control.subprocess, "run", fake_run)
    monkeypatch.setattr(
        master_control,
        "verify_node_registered",
        lambda node_id, min_heartbeat_after, wait_seconds, interval_seconds: (True, "verified"),
    )

    master_app_client.put("/api/master/providers/active", json={"provider": "static"})
    provision = master_app_client.post("/api/master/provision/run", json={"dry_run": False})
    assert provision.status_code == 200

    assert captured["timeout"] == 55
    cmd = captured["cmd"]
    assert isinstance(cmd, list)
    assert "echo cfg-boot worker-c; echo cfg-start 7" in cmd


def test_master_provision_non_dry_run_fails_when_registration_not_verified(master_app_client: TestClient, tmp_path: Path, monkeypatch):
    server_list = tmp_path / "servers.json"
    server_list.write_text(
        json.dumps(
            {
                "servers": [
                    {
                        "node_id": "worker-d",
                        "host": "10.0.0.13",
                        "username": "root",
                        "max_profiles": 6,
                        "enabled": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(master_control, "SERVER_LIST_PATH", server_list)
    monkeypatch.setattr(master_control, "PROVISION_CONFIG_PATH", tmp_path / "missing-provision.json")

    def fake_run(cmd, capture_output, text, check, timeout, env=None):
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(master_control.subprocess, "run", fake_run)
    monkeypatch.setattr(
        master_control,
        "verify_node_registered",
        lambda node_id, min_heartbeat_after, wait_seconds, interval_seconds: (False, "no heartbeat"),
    )

    master_app_client.put("/api/master/providers/active", json={"provider": "static"})
    provision = master_app_client.post("/api/master/provision/run", json={"dry_run": False})
    assert provision.status_code == 200
    data = provision.json()
    assert data["job"]["status"] == "failed"
    assert data["items"][0]["status"] == "failed"
    assert "no heartbeat" in (data["items"][0]["message"] or "")


def test_master_provision_supports_password_with_sshpass(master_app_client: TestClient, tmp_path: Path, monkeypatch):
    server_list = tmp_path / "servers.json"
    server_list.write_text(
        json.dumps(
            {
                "servers": [
                    {
                        "node_id": "worker-pw",
                        "host": "10.0.0.21",
                        "username": "root",
                        "password": "secret",
                        "enabled": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(master_control, "SERVER_LIST_PATH", server_list)
    monkeypatch.setattr(master_control, "PROVISION_CONFIG_PATH", tmp_path / "missing-provision.json")
    monkeypatch.setattr(master_control.shutil, "which", lambda name: "/usr/bin/sshpass" if name == "sshpass" else None)

    captured: dict[str, object] = {}

    def fake_run(cmd, capture_output, text, check, timeout, env=None):
        captured["cmd"] = cmd
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(master_control.subprocess, "run", fake_run)
    monkeypatch.setattr(master_control, "verify_node_registered", lambda *args, **kwargs: (True, "verified"))

    master_app_client.put("/api/master/providers/active", json={"provider": "static"})
    provision = master_app_client.post("/api/master/provision/run", json={"dry_run": False})
    assert provision.status_code == 200
    cmd = captured["cmd"]
    assert isinstance(cmd, list)
    assert cmd[0] == "/usr/bin/sshpass"
    assert cmd[1] == "-p"
    assert cmd[2] == "secret"


def test_master_provision_parallel_isolated_failures(master_app_client: TestClient, tmp_path: Path, monkeypatch):
    server_list = tmp_path / "servers.json"
    server_list.write_text(
        json.dumps(
            {
                "servers": [
                    {"node_id": "worker-1", "host": "10.0.0.31", "username": "root", "enabled": True},
                    {"node_id": "worker-2", "host": "10.0.0.32", "username": "root", "enabled": True},
                ]
            }
        ),
        encoding="utf-8",
    )
    provision_cfg = tmp_path / "provision.json"
    provision_cfg.write_text(
        json.dumps({"timeout_seconds": 15, "max_parallel": 2, "bootstrap_cmd": "echo boot", "start_cmd": "echo start"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(master_control, "SERVER_LIST_PATH", server_list)
    monkeypatch.setattr(master_control, "PROVISION_CONFIG_PATH", provision_cfg)

    def fake_run(cmd, capture_output, text, check, timeout, env=None):
        if any("10.0.0.32" in str(part) for part in cmd):
            return SimpleNamespace(returncode=1, stdout="", stderr="boom")
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(master_control.subprocess, "run", fake_run)
    monkeypatch.setattr(master_control, "verify_node_registered", lambda *args, **kwargs: (True, "verified"))

    master_app_client.put("/api/master/providers/active", json={"provider": "static"})
    provision = master_app_client.post("/api/master/provision/run", json={"dry_run": False})
    assert provision.status_code == 200
    data = provision.json()
    assert data["job"]["status"] == "partial_success"
    assert len(data["items"]) == 2
    states = sorted(item["status"] for item in data["items"])
    assert states == ["failed", "success"]


def test_master_provision_supports_password_with_askpass_fallback(master_app_client: TestClient, tmp_path: Path, monkeypatch):
    server_list = tmp_path / "servers.json"
    server_list.write_text(
        json.dumps(
            {
                "servers": [
                    {
                        "node_id": "worker-pw-askpass",
                        "host": "10.0.0.22",
                        "username": "root",
                        "password": "secret2",
                        "enabled": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(master_control, "SERVER_LIST_PATH", server_list)
    monkeypatch.setattr(master_control, "PROVISION_CONFIG_PATH", tmp_path / "missing-provision.json")
    monkeypatch.setattr(master_control.shutil, "which", lambda name: None)

    captured: dict[str, object] = {}

    def fake_run(cmd, capture_output, text, check, timeout, env=None):
        captured["cmd"] = cmd
        captured["env"] = env
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(master_control.subprocess, "run", fake_run)
    monkeypatch.setattr(master_control, "verify_node_registered", lambda *args, **kwargs: (True, "verified"))

    master_app_client.put("/api/master/providers/active", json={"provider": "static"})
    provision = master_app_client.post("/api/master/provision/run", json={"dry_run": False})
    assert provision.status_code == 200

    cmd = captured["cmd"]
    env = captured["env"]
    assert isinstance(cmd, list)
    assert cmd[0] == "setsid"
    assert isinstance(env, dict)
    assert env.get("SSH_ASKPASS")
    assert env.get("SSH_PASSWORD") == "secret2"
