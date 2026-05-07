from __future__ import annotations

import os
from typing import Any


INFRA_FIELD_MAPPING: dict[str, str] = {
    "node_id": "node_id",
    "host": "host",
    "ssh_user": "ssh_user",
    "ssh_password": "ssh_password",
    "ssh_port": "ssh_port",
    "enabled": "enabled",
    "desired_state": "desired_state",
    "max_profiles": "max_profiles",
    "region": "region",
    "tags": "tags",
    "worker_api_base": "worker_api_base",
    "notes": "notes",
}

BIZ_FIELD_MAPPING: dict[str, str] = {
    "job_key": "job_key",
    "source_record_id": "source_record_id",
    "enabled": "enabled",
    "status": "status",
    "run_generation": "run_generation",
    "script_key": "script_key",
    "script_version": "script_version",
    "account": "account",
    "target_url": "target_url",
    "profile_name": "profile_name",
    "worker_tags": "worker_tags",
    "priority": "priority",
    "max_retries": "max_retries",
    "params": "params",
}

WRITEBACK_FIELD_MAPPING: dict[str, str] = {
    "status": "status",
    "result_summary": "result_summary",
    "error_message": "error_message",
    "master_task_id": "master_task_id",
    "assigned_worker": "assigned_worker",
    "profile_id": "profile_id",
    "last_run_at": "last_run_at",
}

REQUIRED_ENV = (
    "FEISHU_APP_ID",
    "FEISHU_APP_SECRET",
    "FEISHU_INFRA_APP_TOKEN",
    "FEISHU_INFRA_TABLE_ID",
    "FEISHU_BIZ_APP_TOKEN",
    "FEISHU_BIZ_TABLE_ID",
)


def contract_summary() -> dict[str, Any]:
    return {
        "provider": "feishu_openapi",
        "input_schema_version": "v1",
        "required_env": list(REQUIRED_ENV),
        "infra_field_mapping": INFRA_FIELD_MAPPING,
        "biz_field_mapping": BIZ_FIELD_MAPPING,
        "writeback_field_mapping": WRITEBACK_FIELD_MAPPING,
        "idempotency": "source_record_id + run_generation",
        "sync_cursor": "updated_at or record_id cursor, persisted per source in future adapters",
        "secrets": [
            "FEISHU_APP_SECRET",
            "ssh_password",
            "params.password",
        ],
    }


def validate_config(env: dict[str, str] | None = None) -> dict[str, Any]:
    env = env or os.environ
    missing = [name for name in REQUIRED_ENV if not env.get(name)]
    message = "feishu_openapi is configured"
    if missing:
        message = f"feishu_openapi provider is not configured yet; missing env: {', '.join(missing)}"
    return {
        "provider": "feishu_openapi",
        "ready": not missing,
        "missing_env": missing,
        "message": message,
        "contract": contract_summary(),
    }
