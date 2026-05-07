from __future__ import annotations

from typing import Any

SECRET_KEYS = {
    "password",
    "passwd",
    "pwd",
    "secret",
    "token",
    "access_token",
    "refresh_token",
    "app_secret",
    "ssh_password",
}


def is_secret_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return normalized in SECRET_KEYS or normalized.endswith("_password") or normalized.endswith("_secret") or normalized.endswith("_token")


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: ("***" if is_secret_key(str(key)) else redact(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value
