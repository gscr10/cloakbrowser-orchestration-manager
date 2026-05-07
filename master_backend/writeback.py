from __future__ import annotations

from typing import Any

from . import source_registry
from .source_adapters import WriteBackSink

_sink: WriteBackSink | None = None


def get_sink() -> WriteBackSink:
    if _sink is not None:
        return _sink
    return source_registry.get_writeback_sink()


def set_sink(sink: WriteBackSink) -> None:
    global _sink
    _sink = sink


def write_biz_status(job: dict[str, Any], status: str, payload: dict[str, Any]) -> dict[str, Any]:
    return get_sink().write_biz_status(job, status, payload)
