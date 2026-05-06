from __future__ import annotations

from typing import Any

from .source_adapters import NoopWriteBackSink, WriteBackSink

_sink: WriteBackSink = NoopWriteBackSink()


def get_sink() -> WriteBackSink:
    return _sink


def set_sink(sink: WriteBackSink) -> None:
    global _sink
    _sink = sink


def write_biz_status(job: dict[str, Any], status: str, payload: dict[str, Any]) -> dict[str, Any]:
    return get_sink().write_biz_status(job, status, payload)
