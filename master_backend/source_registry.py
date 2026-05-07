from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import database as db
from . import feishu_contract
from .feishu_openapi import FeishuBitableClient
from .source_adapters import FeishuOpenApiSource, LocalJsonSource, NoopWriteBackSink, WriteBackSink


DEFAULT_INFRA_PATH = Path(os.environ.get("MASTER_INFRA_WORKERS_PATH", "/config/infra_workers.json"))
DEFAULT_BIZ_PATH = Path(os.environ.get("MASTER_BIZ_TASKS_PATH", "/config/biz_tasks.json"))
DEFAULT_WRITEBACK_SINK = os.environ.get("MASTER_WRITEBACK_SINK", "noop")
ACTIVE_WRITEBACK_SINK_KEY = "master.writeback_sink"


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


def get_active_writeback_sink_name() -> str:
    return db.get_master_setting(ACTIVE_WRITEBACK_SINK_KEY) or DEFAULT_WRITEBACK_SINK


def set_active_writeback_sink_name(name: str) -> str:
    if name == "feishu_openapi":
        validation = feishu_contract.validate_config()
        if not validation["ready"]:
            raise ValueError(validation["message"])
    elif name != "noop":
        raise ValueError(f"unsupported write-back sink: {name}")
    db.set_master_setting(ACTIVE_WRITEBACK_SINK_KEY, name)
    return name


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
        client = FeishuBitableClient()
        validation = client.validate()
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
        record_id = job.get("feishu_record_id") or job.get("source_record_id")
        if not record_id:
            return {
                "sink": self.name,
                "written": False,
                "job_id": job.get("id"),
                "status": status,
                "reason": "job does not have a Feishu record id",
                "payload": payload,
            }
        fields = _writeback_fields(job, status, payload)
        response = client.update_biz_record(str(record_id), fields)
        return {
            "sink": self.name,
            "written": True,
            "job_id": job.get("id"),
            "source_record_id": job.get("source_record_id"),
            "status": status,
            "fields": fields,
            "response": response,
            "payload": payload,
        }


def get_writeback_sink(name: str | None = None) -> WriteBackSink:
    selected = name or get_active_writeback_sink_name()
    if selected == "noop":
        return NoopWriteBackSink()
    if selected == "feishu_openapi":
        return FeishuOpenApiWriteBackSink()
    raise ValueError(f"unsupported write-back sink: {selected}")


def _writeback_fields(job: dict[str, Any], status: str, payload: dict[str, Any]) -> dict[str, Any]:
    mapping = feishu_contract.WRITEBACK_FIELD_MAPPING
    fields: dict[str, Any] = {
        mapping["status"]: status,
        mapping["master_task_id"]: payload.get("master_task_id") or job.get("master_task_id"),
        mapping["assigned_worker"]: job.get("assigned_worker"),
        mapping["profile_id"]: job.get("profile_id"),
        mapping["last_run_at"]: job.get("last_run_at"),
    }
    if status == "success":
        fields[mapping["result_summary"]] = payload.get("result_summary")
    else:
        fields[mapping["error_message"]] = payload.get("error_message")
    return {key: value for key, value in fields.items() if value is not None}
