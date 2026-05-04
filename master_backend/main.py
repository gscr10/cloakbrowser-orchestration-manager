"""Independent Master control-plane API service."""

from __future__ import annotations

import datetime as dt
import hmac
import logging
import os
from contextlib import asynccontextmanager
from http.cookies import SimpleCookie

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from . import database as db
from . import master_control
from .models import (
    MasterNodeHeartbeatRequest,
    MasterNodeRegisterRequest,
    MasterProviderUpdateRequest,
    MasterProvisionRunRequest,
    MasterTaskCreateRequest,
    MasterTaskPullRequest,
    MasterTaskReportRequest,
)

logger = logging.getLogger("cloakbrowser.master")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

AUTH_TOKEN: str | None = os.environ.get("AUTH_TOKEN") or None
_AUTH_EXEMPT = frozenset({"/api/status"})


def _check_auth(scope: Scope) -> bool:
    for key, val in scope.get("headers", []):
        if key == b"authorization":
            auth_value = val.decode()
            if auth_value.startswith("Bearer "):
                token = auth_value[7:]
                if token and AUTH_TOKEN and hmac.compare_digest(token, AUTH_TOKEN):
                    return True
            break
    for key, val in scope.get("headers", []):
        if key == b"cookie":
            cookies = SimpleCookie()
            cookies.load(val.decode())
            if "auth_token" in cookies:
                cookie_val = cookies["auth_token"].value
                if cookie_val and AUTH_TOKEN and hmac.compare_digest(cookie_val, AUTH_TOKEN):
                    return True
            break
    return False


class AuthMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if not AUTH_TOKEN or scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope["path"]
        if path in _AUTH_EXEMPT or not path.startswith("/api/"):
            await self.app(scope, receive, send)
            return
        if _check_auth(scope):
            await self.app(scope, receive, send)
            return
        response = JSONResponse({"detail": "Unauthorized"}, status_code=401)
        await response(scope, receive, send)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.init_db()
    logger.info("Master backend started")
    yield


app = FastAPI(title="CloakBrowser Master API", lifespan=lifespan)
app.add_middleware(AuthMiddleware)


@app.get("/api/status")
async def status():
    return {"service": "master", "ok": True}


@app.post("/api/master/nodes/register")
async def master_register_node(req: MasterNodeRegisterRequest):
    node = db.upsert_master_node(
        node_id=req.node_id,
        hostname=req.hostname,
        api_base=req.api_base,
        token=req.token,
        tags=req.tags,
        max_profiles=req.max_profiles,
        running_profiles=0,
        status="online",
    )
    return {"node": node}


@app.post("/api/master/nodes/heartbeat")
async def master_node_heartbeat(req: MasterNodeHeartbeatRequest):
    existing = db.get_master_node(req.node_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Node not registered")
    node = db.upsert_master_node(
        node_id=req.node_id,
        hostname=existing["hostname"],
        api_base=existing.get("api_base"),
        token=existing.get("token"),
        tags=existing.get("tags") or [],
        max_profiles=int(existing.get("max_profiles") or 15),
        running_profiles=req.running_profiles,
        cpu_percent=req.cpu_percent,
        mem_total_mb=req.mem_total_mb,
        mem_used_mb=req.mem_used_mb,
        status=req.status,
    )
    return {"node": node}


@app.get("/api/master/nodes")
async def master_list_nodes():
    return db.list_master_nodes()


@app.get("/api/master/cluster/status")
async def master_cluster_status():
    nodes = db.list_master_nodes()
    now = dt.datetime.now(dt.timezone.utc)
    ttl = master_control.NODE_HEARTBEAT_TTL_SECONDS
    normalized_nodes = []
    for node in nodes:
        node_view = dict(node)
        hb_raw = node.get("last_heartbeat_at")
        try:
            hb = dt.datetime.fromisoformat(hb_raw) if hb_raw else None
        except ValueError:
            hb = None
        if hb and (now - hb).total_seconds() > ttl and node_view.get("status") == "online":
            node_view["status"] = "stale"
        normalized_nodes.append(node_view)
    tasks = db.list_master_tasks()
    queued = len([task for task in tasks if task["status"] == "queued"])
    dispatched = len([task for task in tasks if task["status"] == "dispatched"])
    running = len([task for task in tasks if task["status"] == "running"])
    return {
        "nodes": normalized_nodes,
        "tasks": {
            "queued": queued,
            "dispatched": dispatched,
            "running": running,
            "total": len(tasks),
        },
    }


@app.get("/api/master/tasks")
async def master_list_tasks():
    return db.list_master_tasks()


@app.get("/api/master/tasks/{task_id}")
async def master_get_task(task_id: str):
    task = db.get_master_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@app.get("/api/master/tasks/{task_id}/events")
async def master_get_task_events(task_id: str):
    task = db.get_master_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return db.list_master_task_events(task_id)


@app.post("/api/master/tasks", status_code=201)
async def master_create_task(req: MasterTaskCreateRequest):
    payload = req.model_dump()
    if payload.get("task_type") == "open_url" and not (payload.get("url") or "").strip():
        payload["url"] = "https://www.baidu.com"
    task = master_control.create_master_task(payload)
    db.create_master_task_event(task["id"], None, "queued", "created by master")
    return task


@app.post("/api/master/tasks/pull")
async def master_pull_task(req: MasterTaskPullRequest):
    node = db.get_master_node(req.node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not registered")
    task = db.allocate_master_task(req.node_id)
    if not task:
        return {"task": None}
    return {"task": task}


@app.post("/api/master/tasks/{task_id}/report")
async def master_report_task(task_id: str, req: MasterTaskReportRequest):
    task = db.get_master_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.get("target_node_id") and task["target_node_id"] != req.node_id:
        raise HTTPException(status_code=409, detail="Task belongs to another node")
    if req.dispatch_id and task.get("dispatch_id") and req.dispatch_id != task.get("dispatch_id"):
        raise HTTPException(status_code=409, detail="dispatch_id mismatch")
    mapped = {
        "started": "running",
        "success": "success",
        "failed": "failed",
    }[req.status]
    if req.status == "failed":
        retry_count = int(task.get("retry_count") or 0)
        max_retries = int(task.get("max_retries") or 0)
        if retry_count < max_retries:
            target = master_control.pick_target_node()
            updated = db.update_master_task(
                task_id,
                status="queued",
                retry_count=retry_count + 1,
                dispatch_id=None,
                failure_reason=req.failure_reason,
                target_node_id=target["node_id"] if target else task.get("target_node_id"),
            )
            db.create_master_task_event(task_id, req.node_id, "retry_scheduled", req.failure_reason)
            return updated
    updated = db.update_master_task(task_id, status=mapped, failure_reason=req.failure_reason)
    db.create_master_task_event(task_id, req.node_id, req.status, req.failure_reason)
    return updated


@app.get("/api/master/providers")
async def master_list_providers():
    active = master_control.get_active_provider_name()
    providers = list(master_control.available_providers().keys())
    return {"active": active, "providers": providers}


@app.put("/api/master/providers/active")
async def master_set_provider(req: MasterProviderUpdateRequest):
    try:
        active = master_control.set_active_provider_name(req.provider)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"active": active}


@app.post("/api/master/providers/feishu-cli/validate")
async def master_validate_feishu_cli_provider():
    return {
        "provider": "feishu_cli",
        "ready": False,
        "message": "feishu_cli provider is reserved and not implemented yet",
    }


@app.post("/api/master/provision/run")
async def master_run_provision(req: MasterProvisionRunRequest):
    try:
        return master_control.run_provision(dry_run=req.dry_run)
    except NotImplementedError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/master/provision/jobs")
async def master_list_provision_jobs():
    return db.list_provision_jobs()


@app.get("/api/master/provision/jobs/{job_id}")
async def master_get_provision_job(job_id: str):
    job = db.get_provision_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Provision job not found")
    return {"job": job, "items": db.list_provision_job_items(job_id)}
