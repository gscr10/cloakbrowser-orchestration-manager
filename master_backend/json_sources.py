from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_items(path: Path, key: str) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    items = raw.get(key, raw) if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        raise ValueError(f"{path} must contain a list or a '{key}' list")
    return [item for item in items if isinstance(item, dict)]
