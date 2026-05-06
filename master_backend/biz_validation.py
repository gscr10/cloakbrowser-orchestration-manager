from __future__ import annotations

from typing import Any


_REQUIRED_FIELDS: dict[tuple[str, str], tuple[str, ...]] = {
    ("open_url", "v1"): ("target_url",),
    ("itp_login_ticket", "v1"): ("target_url", "account"),
}


def list_input_schemas() -> list[dict[str, Any]]:
    return [
        {
            "script_key": script_key,
            "script_version": script_version,
            "input_schema_version": "v1",
            "required_fields": list(required),
        }
        for (script_key, script_version), required in sorted(_REQUIRED_FIELDS.items())
    ]


def validate_job_payload(job: dict[str, Any]) -> tuple[bool, str | None]:
    script_key = str(job.get("script_key") or "").strip()
    script_version = str(job.get("script_version") or "v1").strip() or "v1"
    required = _REQUIRED_FIELDS.get((script_key, script_version))
    if required is None:
        return False, f"unsupported automation script: {script_key}@{script_version}"
    params = job.get("params") or job.get("biz_params") or {}
    if not isinstance(params, dict):
        params = {}
    missing = []
    for field in required:
        value = job.get(field)
        if value is None:
            value = params.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            missing.append(field)
    if missing:
        return False, f"missing required fields for {script_key}@{script_version}: {', '.join(missing)}"
    return True, None
