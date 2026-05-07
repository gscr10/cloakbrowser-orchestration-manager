from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import feishu_contract
from .source_adapters import FeishuOpenApiSource, LocalJsonSource, NoopWriteBackSink, WriteBackSink


DEFAULT_INFRA_PATH = Path(os.environ.get("MASTER_INFRA_WORKERS_PATH", "/config/infra_workers.json"))
DEFAULT_BIZ_PATH = Path(os.environ.get("MASTER_BIZ_TASKS_PATH", "/config/biz_tasks.json"))
DEFAULT_WRITEBACK_SINK = os.environ.get("MASTER_WRITEBACK_SINK", "noop")


@dataclass(frozen=True)
class SourceDescriptor:
    name: str
    kind: str
    ready: bool
    message: str
    config: dict[str, Any]


@dataclass(frozen=True)
class SinkDescriptor:
    name: str
    ready: bool
    message: str
    config: dict[str, Any]


def _local_json_descriptor(kind: str, path: Path) -> SourceDescriptor:
    return SourceDescriptor(
        name="local_json",
        kind=kind,
        ready=path.exists(),
        message=f"reading {path}",
        config={"path": str(path)},
    )


def list_sources() -> list[dict[str, Any]]:
    feishu = feishu_contract.validate_config()
    return [
        _local_json_descriptor("infra", DEFAULT_INFRA_PATH).__dict__,
        _local_json_descriptor("biz", DEFAULT_BIZ_PATH).__dict__,
        {
            "name": "feishu_openapi",
            "kind": "infra_biz",
            "ready": feishu["ready"],
            "message": feishu["message"],
            "config": {"missing_env": feishu["missing_env"], "contract": feishu["contract"]},
        },
    ]


def list_sinks() -> list[dict[str, Any]]:
    feishu = feishu_contract.validate_config()
    return [
        SinkDescriptor(
            name="noop",
            ready=True,
            message="write-back is recorded as skipped events only",
            config={},
        ).__dict__,
        SinkDescriptor(
            name="feishu_openapi",
            ready=feishu["ready"],
            message=feishu["message"],
            config={"missing_env": feishu["missing_env"], "contract": feishu["contract"]},
        ).__dict__,
    ]


def build_local_json_source(
    infra_workers_path: Path | None = None,
    biz_tasks_path: Path | None = None,
) -> LocalJsonSource:
    return LocalJsonSource(
        infra_workers_path=infra_workers_path or DEFAULT_INFRA_PATH,
        biz_tasks_path=biz_tasks_path or DEFAULT_BIZ_PATH,
    )


def get_infra_source(name: str = "local_json", path: Path | None = None) -> LocalJsonSource | FeishuOpenApiSource:
    if name == "local_json":
        return build_local_json_source(infra_workers_path=path)
    if name == "feishu_openapi":
        return FeishuOpenApiSource()
    raise ValueError(f"unsupported infra source: {name}")


def get_biz_source(name: str = "local_json", path: Path | None = None) -> LocalJsonSource | FeishuOpenApiSource:
    if name == "local_json":
        return build_local_json_source(biz_tasks_path=path)
    if name == "feishu_openapi":
        return FeishuOpenApiSource()
    raise ValueError(f"unsupported biz source: {name}")


class FeishuOpenApiWriteBackSink(NoopWriteBackSink):
    name = "feishu_openapi"

    def write_biz_status(self, job: dict[str, Any], status: str, payload: dict[str, Any]) -> dict[str, Any]:
        validation = feishu_contract.validate_config()
        if not validation["ready"]:
            return {
                "sink": self.name,
                "written": False,
                "job_id": job.get("id"),
                "source_record_id": job.get("source_record_id"),
                "status": status,
                "reason": validation["message"],
                "missing_env": validation["missing_env"],
                "payload": payload,
            }
        return {
            "sink": self.name,
            "written": False,
            "job_id": job.get("id"),
            "source_record_id": job.get("source_record_id"),
            "status": status,
            "reason": "Feishu OpenAPI HTTP writer contract is configured but network writer is not implemented",
            "payload": payload,
        }


def get_writeback_sink(name: str | None = None) -> WriteBackSink:
    selected = name or DEFAULT_WRITEBACK_SINK
    if selected == "noop":
        return NoopWriteBackSink()
    if selected == "feishu_openapi":
        return FeishuOpenApiWriteBackSink()
    raise ValueError(f"unsupported write-back sink: {selected}")
