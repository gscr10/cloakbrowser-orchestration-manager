from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class MasterNodeRegisterRequest(BaseModel):
    node_id: str
    hostname: str
    api_base: str | None = None
    token: str | None = None
    tags: list[str] = Field(default_factory=list)
    max_profiles: int = Field(default=15, ge=1, le=15)


class MasterNodeHeartbeatRequest(BaseModel):
    node_id: str
    running_profiles: int = Field(default=0, ge=0)
    cpu_percent: float | None = Field(default=None, ge=0, le=100)
    mem_total_mb: int | None = Field(default=None, ge=0)
    mem_used_mb: int | None = Field(default=None, ge=0)
    status: Literal["online", "offline", "degraded"] = "online"


class MasterTaskCreateRequest(BaseModel):
    profile_id: str | None = None
    authorized_target: str
    task_type: Literal["open_url", "external_cdp"] = "open_url"
    url: str | None = None
    timeout_seconds: int = Field(default=300, ge=1, le=86400)
    max_retries: int = Field(default=1, ge=0, le=10)

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


class MasterProviderUpdateRequest(BaseModel):
    provider: str


class MasterProvisionRunRequest(BaseModel):
    dry_run: bool = True
