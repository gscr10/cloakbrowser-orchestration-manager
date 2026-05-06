from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .json_sources import load_items


class InfraSource(Protocol):
    name: str

    def list_workers(self) -> list[dict[str, Any]]:
        ...


class BizSource(Protocol):
    name: str

    def list_jobs(self) -> list[dict[str, Any]]:
        ...


class WriteBackSink(Protocol):
    name: str

    def write_biz_status(self, job: dict[str, Any], status: str, payload: dict[str, Any]) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class LocalJsonSource:
    infra_workers_path: Path
    biz_tasks_path: Path
    name: str = "local_json"

    def list_workers(self) -> list[dict[str, Any]]:
        return load_items(self.infra_workers_path, "workers")

    def list_jobs(self) -> list[dict[str, Any]]:
        return load_items(self.biz_tasks_path, "jobs")


class FeishuOpenApiSource:
    name = "feishu_openapi"

    def list_workers(self) -> list[dict[str, Any]]:
        raise NotImplementedError("Feishu OpenAPI infra source is not configured yet")

    def list_jobs(self) -> list[dict[str, Any]]:
        raise NotImplementedError("Feishu OpenAPI biz source is not configured yet")


class NoopWriteBackSink:
    name = "noop"

    def write_biz_status(self, job: dict[str, Any], status: str, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "sink": self.name,
            "written": False,
            "job_id": job.get("id"),
            "status": status,
            "reason": "write-back sink is not configured",
            "payload": payload,
        }
