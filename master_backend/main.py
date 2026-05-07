"""Independent Master control-plane API service."""

from __future__ import annotations

import datetime as dt
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import architecture
from . import biz_repository
from . import biz_services
from . import biz_sync
from . import biz_validation
from . import database as db
from . import infra_repository
from . import infra_services
from . import infra_sync
from . import master_control
from .models import (
    MasterNodeHeartbeatRequest,
    MasterNodeRegisterRequest,
    MasterProviderUpdateRequest,
    MasterProvisionRunRequest,
    MasterSyncRequest,
    MasterTaskCreateRequest,
    MasterTaskPullRequest,
    MasterTaskReportRequest,
)

logger = logging.getLogger("cloakbrowser.master")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.init_db()
    logger.info("Master backend started")
    yield


app = FastAPI(title="CloakBrowser Master API", lifespan=lifespan)

MASTER_FRONTEND_DIR = Path(__file__).parent.parent / "master-frontend" / "dist"
if MASTER_FRONTEND_DIR.exists():
    assets_dir = MASTER_FRONTEND_DIR / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="master-assets")


@app.get("/api/status")
async def status():
    return {"service": "master", "ok": True}


@app.post("/api/master/nodes/register")
async def master_register_node(req: MasterNodeRegisterRequest):
    node = db.upsert_master_node(
        node_id=req.node_id,
        hostname=req.hostname,
        api_base=req.api_base,
        token=None,
        tags=req.tags,
        max_profiles=req.max_profiles,
        running_profiles=0,
        status="online",
    )
    infra_services.record_worker_registration(
        req.node_id,
        [cap.model_dump() for cap in req.capabilities],
        hostname=req.hostname,
        api_base=req.api_base,
        tags=req.tags,
        max_profiles=req.max_profiles,
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
        token=None,
        tags=existing.get("tags") or [],
        max_profiles=int(existing.get("max_profiles") or 15),
        running_profiles=req.running_profiles,
        cpu_percent=req.cpu_percent,
        mem_total_mb=req.mem_total_mb,
        mem_used_mb=req.mem_used_mb,
        status=req.status,
    )
    infra_services.record_worker_heartbeat(
        req.node_id,
        req.status,
        req.running_profiles,
        req.cpu_percent,
        req.mem_total_mb,
        req.mem_used_mb,
        node.get("last_heartbeat_at"),
        [profile.model_dump() for profile in req.profiles],
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
    task = master_control.ensure_task_profile_for_node(task, node)
    biz_services.mark_task_dispatched(task, req.node_id)
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
    payload = task.get("payload") or {}
    if req.status == "started":
        biz_services.mark_task_started(task, req.node_id)
    if req.status == "failed":
        retry_count = int(task.get("retry_count") or 0)
        max_retries = int(task.get("max_retries") or 0)
        if retry_count < max_retries:
            if payload.get("task_type") == "automation_script":
                required_capabilities = []
                if payload.get("script_key"):
                    required_capabilities.append(
                        {
                            "script_key": payload.get("script_key"),
                            "script_version": payload.get("script_version") or "v1",
                        }
                    )
                target = infra_services.find_available_worker(
                    worker_tags=payload.get("worker_tags") or [],
                    required_capabilities=required_capabilities,
                )
            else:
                target = master_control.pick_target_node()
            retry_fields: dict[str, object | None] = {
                "status": "queued",
                "retry_count": retry_count + 1,
                "dispatch_id": None,
                "failure_reason": req.failure_reason,
                "target_node_id": target["node_id"] if target else task.get("target_node_id"),
            }
            if payload.get("profile_id"):
                next_payload = dict(payload)
                next_payload.pop("profile_id", None)
                retry_fields["profile_id"] = None
                retry_fields["payload_json"] = json.dumps(next_payload)
            updated = db.update_master_task(task_id, **retry_fields)
            db.create_master_task_event(task_id, req.node_id, "retry_scheduled", req.failure_reason)
            biz_services.mark_task_retrying(task, req.node_id, req.failure_reason)
            return updated
    update_fields = {"status": mapped, "failure_reason": req.failure_reason}
    if req.result:
        next_payload = dict(payload)
        next_payload["result"] = req.result
        update_fields["payload_json"] = json.dumps(next_payload)
    updated = db.update_master_task(task_id, **update_fields)
    db.create_master_task_event(task_id, req.node_id, req.status, req.failure_reason)
    if req.status in {"success", "failed"}:
        biz_services.mark_task_finished(task, req.node_id, req.status, result=dict(req.result), failure_reason=req.failure_reason)
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


@app.post("/api/master/providers/feishu-openapi/validate")
async def master_validate_feishu_openapi_provider():
    return {
        "provider": "feishu_openapi",
        "ready": False,
        "message": "feishu_openapi provider is not configured yet",
    }


@app.get("/api/master/architecture/summary")
async def master_architecture_summary():
    return architecture.architecture_summary()


@app.post("/api/master/infra/sync")
async def master_sync_infra_workers():
    try:
        result = infra_sync.sync_infra_workers()
        result["workers"] = infra_repository.public_worker_views(result.get("workers") or [])
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/master/infra/workers")
async def master_list_infra_workers():
    return infra_repository.public_worker_views(infra_repository.list_workers())


@app.get("/api/master/infra/events")
async def master_list_infra_events():
    return infra_repository.list_events()


@app.get("/api/master/infra/sync-runs")
async def master_list_infra_sync_runs():
    return infra_repository.list_sync_runs()


@app.get("/api/master/infra/capabilities")
async def master_list_infra_capabilities():
    return infra_repository.list_capabilities()


@app.get("/api/master/biz/input-schemas")
async def master_list_biz_input_schemas():
    return biz_validation.list_input_schemas()


@app.get("/api/master/infra/profiles")
async def master_list_infra_profiles():
    return infra_repository.list_profiles()


@app.post("/api/master/biz/sync")
async def master_sync_biz_jobs(req: MasterSyncRequest):
    try:
        result = biz_sync.sync_biz_jobs()
        if req.schedule:
            scheduled = []
            for job in result["jobs"]:
                if job.get("enabled") and not job.get("master_task_id") and job.get("status") != "invalid":
                    scheduled.append(biz_services.schedule_biz_job(job["id"], infra_services.find_available_worker))
            result["scheduled"] = scheduled
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/master/biz/jobs")
async def master_list_biz_jobs():
    return biz_repository.list_jobs()


@app.post("/api/master/biz/jobs/{job_id}/schedule")
async def master_schedule_biz_job(job_id: str):
    try:
        return biz_services.schedule_biz_job(job_id, infra_services.find_available_worker)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get("/api/master/biz/events")
async def master_list_biz_events():
    return biz_repository.list_events()


@app.get("/api/master/biz/runs")
async def master_list_biz_runs():
    return biz_repository.list_runs()


@app.get("/api/master/biz/artifacts")
async def master_list_biz_artifacts():
    return biz_repository.list_artifacts()


@app.post("/api/master/provision/run")
async def master_run_provision(req: MasterProvisionRunRequest):
    try:
        return await run_in_threadpool(master_control.run_provision, dry_run=req.dry_run, node_id=req.node_id)
    except NotImplementedError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.get("/api/master/provision/servers")
async def master_list_provision_servers():
    try:
        return {"provider": master_control.get_active_provider_name(), "servers": master_control.list_servers()}
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


@app.get("/{full_path:path}")
async def master_spa(full_path: str):
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not found")
    if not MASTER_FRONTEND_DIR.exists():
        raise HTTPException(status_code=404, detail="Master frontend build not found")
    requested = MASTER_FRONTEND_DIR / full_path
    if full_path and requested.is_file():
        return FileResponse(str(requested))
    return FileResponse(str(MASTER_FRONTEND_DIR / "index.html"))
