from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class MasterWorkerCapability(BaseModel):
    script_key: str
    script_version: str
    input_schema_version: str = "v1"


class MasterProfileHeartbeat(BaseModel):
    profile_id: str
    status: str = "running"
    vnc_ws_port: int | None = None
    cdp_port: int | None = None
    display: str | None = None
    current_url: str | None = None
    title: str | None = None


class MasterNodeRegisterRequest(BaseModel):
    node_id: str
    hostname: str
    api_base: str | None = None
    tags: list[str] = Field(default_factory=list)
    max_profiles: int = Field(default=15, ge=1, le=15)
    capabilities: list[MasterWorkerCapability] = Field(default_factory=list)


class MasterNodeHeartbeatRequest(BaseModel):
    node_id: str
    running_profiles: int = Field(default=0, ge=0)
    cpu_percent: float | None = Field(default=None, ge=0, le=100)
    mem_total_mb: int | None = Field(default=None, ge=0)
    mem_used_mb: int | None = Field(default=None, ge=0)
    status: Literal["online", "offline", "degraded"] = "online"
    profiles: list[MasterProfileHeartbeat] = Field(default_factory=list)


class MasterTaskCreateRequest(BaseModel):
    profile_id: str | None = None
    authorized_target: str
    task_type: Literal["open_url", "external_cdp", "automation_script"] = "open_url"
    url: str | None = None
    script_key: str | None = None
    script_version: str | None = None
    biz_params: dict[str, object] = Field(default_factory=dict)
    worker_tags: list[str] = Field(default_factory=list)
    timeout_seconds: int = Field(default=300, ge=1, le=86400)
    max_retries: int = Field(default=1, ge=0, le=10)
    priority: int = Field(default=0, ge=0, le=1000)

    @field_validator("authorized_target")
    @classmethod
    def require_authorized_target(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("authorized_target is required")
        return value


class MasterTaskPullRequest(BaseModel):
    node_id: str


class MasterTaskReportRequest(BaseModel):
    node_id: str
    dispatch_id: str | None = None
    status: Literal["started", "success", "failed"]
    failure_reason: str | None = None
    result: dict[str, object] = Field(default_factory=dict)


class MasterProviderUpdateRequest(BaseModel):
    provider: str


class MasterProvisionRunRequest(BaseModel):
    dry_run: bool = True
    node_id: str | None = None


class MasterSyncRequest(BaseModel):
    schedule: bool = False
    source: str = "local_json"


class MasterInfraSyncRequest(BaseModel):
    source: str = "local_json"


class MasterInfraReconcileRequest(BaseModel):
    dry_run: bool = True
    node_id: str | None = None


class MasterStuckTaskRecoveryRequest(BaseModel):
    older_than_seconds: int = Field(default=600, ge=1, le=86400)
