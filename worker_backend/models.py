"""Pydantic models for profile CRUD operations."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class ProfileCreate(BaseModel):
    name: str
    fingerprint_seed: int | None = None  # random if not set
    proxy: str | None = None  # "http://user:pass@host:port" or null
    timezone: str | None = None  # "America/New_York"
    locale: str | None = None  # "en-US"
    platform: Literal["windows", "macos", "linux"] = "windows"
    user_agent: str | None = None
    screen_width: int = 1920
    screen_height: int = 1080
    gpu_vendor: str | None = None
    gpu_renderer: str | None = None
    hardware_concurrency: int | None = None
    humanize: bool = False
    human_preset: Literal["default", "careful"] = "default"
    headless: bool = False
    geoip: bool = False
    clipboard_sync: bool = True
    color_scheme: Literal["light", "dark", "no-preference"] | None = None
    launch_args: list[str] = Field(default_factory=list)
    notes: str | None = None
    tags: list[TagCreate] | None = None


class ProfileUpdate(BaseModel):
    name: str | None = None
    fingerprint_seed: int | None = None
    proxy: str | None = Field(default=None)
    timezone: str | None = Field(default=None)
    locale: str | None = Field(default=None)
    platform: Literal["windows", "macos", "linux"] | None = None
    user_agent: str | None = Field(default=None)
    screen_width: int | None = None
    screen_height: int | None = None
    gpu_vendor: str | None = Field(default=None)
    gpu_renderer: str | None = Field(default=None)
    hardware_concurrency: int | None = Field(default=None)
    humanize: bool | None = None
    human_preset: Literal["default", "careful"] | None = None
    headless: bool | None = None
    geoip: bool | None = None
    clipboard_sync: bool | None = None
    color_scheme: Literal["light", "dark", "no-preference"] | None = Field(default=None)
    launch_args: list[str] | None = None
    notes: str | None = Field(default=None)
    tags: list[TagCreate] | None = None


class TagCreate(BaseModel):
    tag: str
    color: str | None = None  # hex color


class TagResponse(BaseModel):
    tag: str
    color: str | None = None


class ProfileResponse(BaseModel):
    id: str
    name: str
    fingerprint_seed: int
    proxy: str | None = None
    timezone: str | None = None
    locale: str | None = None
    platform: str = "windows"
    user_agent: str | None = None
    screen_width: int = 1920
    screen_height: int = 1080
    gpu_vendor: str | None = None
    gpu_renderer: str | None = None
    hardware_concurrency: int | None = None
    humanize: bool = False
    human_preset: str = "default"
    headless: bool = False
    geoip: bool = False
    clipboard_sync: bool = True

    @field_validator("clipboard_sync", mode="before")
    @classmethod
    def coerce_clipboard_sync(cls, v: object) -> bool:
        return v if v is not None else True

    color_scheme: str | None = None
    launch_args: list[str] = []
    notes: str | None = None
    user_data_dir: str
    created_at: str
    updated_at: str
    tags: list[TagResponse] = []
    status: str = "stopped"  # "running" | "stopped"
    vnc_ws_port: int | None = None
    cdp_url: str | None = None


class LaunchResponse(BaseModel):
    profile_id: str
    status: str = "running"
    vnc_ws_port: int
    display: str
    cdp_url: str | None = None


class StatusResponse(BaseModel):
    running_count: int
    binary_version: str
    profiles_total: int


class ProfileStatusResponse(BaseModel):
    status: str  # "running" | "stopped"
    vnc_ws_port: int | None = None
    display: str | None = None
    cdp_url: str | None = None


class ClipboardRequest(BaseModel):
    text: str = Field(max_length=1_048_576)  # 1MB max


class LoginRequest(BaseModel):
    token: str


class ProxyEndpointCreate(BaseModel):
    name: str | None = None
    protocol: Literal["http", "https", "socks5"] = "http"
    host: str
    port: int = Field(ge=1, le=65535)
    username: str | None = None
    password: str | None = None
    region: str | None = None
    tags: list[str] = Field(default_factory=list)


class ProxyEndpointResponse(BaseModel):
    id: str
    name: str
    protocol: str
    host: str
    port: int
    username: str | None = None
    region: str | None = None
    tags: list[str] = []
    health: str = "unknown"
    created_at: str
    updated_at: str


class ProxyImportRequest(BaseModel):
    csv: str


class ProxyImportError(BaseModel):
    line: int
    error: str


class ProxyImportResponse(BaseModel):
    created: list[ProxyEndpointResponse]
    errors: list[ProxyImportError]


class TaskCreate(BaseModel):
    profile_id: str
    authorized_target: str
    task_type: Literal["open_url", "external_cdp", "automation_script"] = "open_url"
    url: str | None = None
    payload: dict[str, object] = Field(default_factory=dict)
    timeout_seconds: int = Field(default=300, ge=1, le=86400)

    @field_validator("authorized_target")
    @classmethod
    def require_authorized_target(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("authorized_target is required")
        return value.strip()

    @model_validator(mode="after")
    def require_url_for_open_url(self) -> "TaskCreate":
        if self.task_type == "open_url":
            if not self.url or not self.url.strip():
                self.url = "https://www.baidu.com"
            else:
                self.url = self.url.strip()
        return self


class TaskResponse(BaseModel):
    id: str
    profile_id: str
    authorized_target: str
    task_type: str
    url: str | None = None
    status: str
    proxy_id: str | None = None
    run_id: str | None = None
    failure_reason: str | None = None
    payload: dict[str, object] = Field(default_factory=dict)
    created_at: str
    updated_at: str


class RunResponse(BaseModel):
    id: str
    profile_id: str
    task_id: str | None = None
    proxy_id: str | None = None
    status: str
    started_at: str
    stopped_at: str | None = None
    failure_reason: str | None = None


class SchedulerStatusResponse(BaseModel):
    queued_count: int
    running_count: int
    max_running: int

