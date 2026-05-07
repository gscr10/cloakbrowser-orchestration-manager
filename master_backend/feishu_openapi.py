from __future__ import annotations

import json
import os
from typing import Any

import httpx

from . import feishu_contract

DEFAULT_BASE_URL = os.environ.get("FEISHU_OPENAPI_BASE_URL", "https://open.feishu.cn")
DEFAULT_TIMEOUT_SECONDS = float(os.environ.get("FEISHU_OPENAPI_TIMEOUT_SECONDS", "15"))


def _env(env: dict[str, str] | None, key: str) -> str | None:
    return (env or os.environ).get(key)


def _plain_value(value: Any) -> Any:
    if isinstance(value, list):
        if all(isinstance(item, dict) and "text" in item for item in value):
            return "".join(str(item.get("text") or "") for item in value)
        return [_plain_value(item) for item in value]
    if isinstance(value, dict):
        if "text" in value:
            return value.get("text")
        if "value" in value:
            return value.get("value")
        return {key: _plain_value(item) for key, item in value.items()}
    return value


def _coerce_json(value: Any) -> Any:
    value = _plain_value(value)
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                return value
    return value


def map_record(record: dict[str, Any], field_mapping: dict[str, str]) -> dict[str, Any]:
    fields = record.get("fields") if isinstance(record.get("fields"), dict) else {}
    out: dict[str, Any] = {
        "source": "feishu_openapi",
        "source_record_id": record.get("record_id") or record.get("id"),
        "feishu_record_id": record.get("record_id") or record.get("id"),
    }
    for internal_key, external_key in field_mapping.items():
        if external_key not in fields:
            continue
        value = _coerce_json(fields[external_key])
        if internal_key in {"tags", "worker_tags"} and isinstance(value, str):
            value = [item.strip() for item in value.split(",") if item.strip()]
        if internal_key in {"enabled"} and isinstance(value, str):
            value = value.lower() in {"1", "true", "yes", "on", "enabled", "active"}
        if internal_key in {"ssh_port", "max_profiles", "run_generation", "priority", "max_retries"} and value not in {None, ""}:
            value = int(value)
        out[internal_key] = value
    return out


class FeishuBitableClient:
    def __init__(self, env: dict[str, str] | None = None, http_client: httpx.Client | None = None) -> None:
        self.env = env
        self.http_client = http_client
        self.base_url = _env(env, "FEISHU_OPENAPI_BASE_URL") or DEFAULT_BASE_URL
        self.timeout = float(_env(env, "FEISHU_OPENAPI_TIMEOUT_SECONDS") or DEFAULT_TIMEOUT_SECONDS)
        self._token: str | None = None

    def validate(self) -> dict[str, Any]:
        return feishu_contract.validate_config(self.env)

    def _required(self, key: str) -> str:
        value = _env(self.env, key)
        if not value:
            raise NotImplementedError("Feishu OpenAPI source is not configured yet")
        return value

    def _client(self) -> httpx.Client:
        return self.http_client or httpx.Client(base_url=self.base_url, timeout=self.timeout)

    def _tenant_access_token(self) -> str:
        if self._token:
            return self._token
        app_id = self._required("FEISHU_APP_ID")
        app_secret = self._required("FEISHU_APP_SECRET")
        client = self._client()
        should_close = self.http_client is None
        try:
            resp = client.post(
                "/open-apis/auth/v3/tenant_access_token/internal",
                json={"app_id": app_id, "app_secret": app_secret},
            )
            resp.raise_for_status()
            body = resp.json()
        finally:
            if should_close:
                client.close()
        token = body.get("tenant_access_token") or body.get("app_access_token")
        if not token:
            raise RuntimeError(f"Feishu token response did not include an access token: {body}")
        self._token = str(token)
        return self._token

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._tenant_access_token()}"}

    def list_records(self, app_token: str, table_id: str) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        page_token: str | None = None
        client = self._client()
        should_close = self.http_client is None
        try:
            while True:
                params: dict[str, Any] = {"page_size": 500}
                if page_token:
                    params["page_token"] = page_token
                resp = client.get(
                    f"/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records",
                    headers=self._headers(),
                    params=params,
                )
                resp.raise_for_status()
                body = resp.json()
                data = body.get("data") or {}
                records.extend(data.get("items") or [])
                if not data.get("has_more"):
                    return records
                page_token = data.get("page_token")
        finally:
            if should_close:
                client.close()

    def list_infra_workers(self) -> list[dict[str, Any]]:
        app_token = self._required("FEISHU_INFRA_APP_TOKEN")
        table_id = self._required("FEISHU_INFRA_TABLE_ID")
        return [map_record(record, feishu_contract.INFRA_FIELD_MAPPING) for record in self.list_records(app_token, table_id)]

    def list_biz_jobs(self) -> list[dict[str, Any]]:
        app_token = self._required("FEISHU_BIZ_APP_TOKEN")
        table_id = self._required("FEISHU_BIZ_TABLE_ID")
        return [map_record(record, feishu_contract.BIZ_FIELD_MAPPING) for record in self.list_records(app_token, table_id)]

    def update_biz_record(self, record_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        app_token = self._required("FEISHU_BIZ_APP_TOKEN")
        table_id = self._required("FEISHU_BIZ_TABLE_ID")
        client = self._client()
        should_close = self.http_client is None
        try:
            resp = client.put(
                f"/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/{record_id}",
                headers=self._headers(),
                json={"fields": fields},
            )
            resp.raise_for_status()
            return resp.json()
        finally:
            if should_close:
                client.close()
