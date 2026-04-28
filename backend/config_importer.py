"""Import external runtime configuration for Docker deployments."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import database as db
from .models import ProfileCreate, ProfileUpdate


DEFAULT_CONFIG_DIR = Path("/config")
PROFILES_FILE = "profiles.json"
PROXIES_FILE = "proxies.csv"


def import_config_dir(config_dir: Path = DEFAULT_CONFIG_DIR) -> dict[str, Any]:
    """Import supported config files from a directory if they exist."""
    result: dict[str, Any] = {
        "config_dir": str(config_dir),
        "profiles": {"created": [], "updated": [], "errors": []},
        "proxies": {"created": [], "skipped": [], "errors": []},
    }
    profiles_path = config_dir / PROFILES_FILE
    proxies_path = config_dir / PROXIES_FILE

    if profiles_path.exists():
        result["profiles"] = import_profiles_json(profiles_path)
    if proxies_path.exists():
        result["proxies"] = import_proxies_csv(proxies_path)
    return result


def import_profiles_json(path: Path) -> dict[str, Any]:
    """Import profile definitions from a JSON file.

    The file accepts either a top-level list or an object with a `profiles` list.
    Profiles are matched by name and updated in place to keep browser data dirs
    stable across container restarts.
    """
    created: list[dict[str, Any]] = []
    updated: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        profiles = raw.get("profiles") if isinstance(raw, dict) else raw
        if not isinstance(profiles, list):
            raise ValueError("profiles.json must be a list or an object with a profiles list")
    except Exception as exc:
        return {"created": created, "updated": updated, "errors": [{"index": 0, "error": str(exc)}]}

    existing_by_name = {profile["name"]: profile for profile in db.list_profiles()}
    for index, item in enumerate(profiles, start=1):
        try:
            if not isinstance(item, dict):
                raise ValueError("profile entry must be an object")
            payload = dict(item)
            name = str(payload.get("name") or "").strip()
            if not name:
                raise ValueError("name is required")
            payload["name"] = name

            existing = existing_by_name.get(name)
            if existing:
                validated = ProfileUpdate(**payload).model_dump(exclude_unset=True)
                updated_profile = db.update_profile(existing["id"], **validated)
                if updated_profile:
                    updated.append(updated_profile)
            else:
                validated = ProfileCreate(**payload).model_dump()
                profile = db.create_profile(**validated)
                created.append(profile)
                existing_by_name[name] = profile
        except (ValueError, TypeError) as exc:
            errors.append({"index": index, "error": str(exc)})
        except Exception as exc:
            errors.append({"index": index, "error": str(exc)})
    return {"created": created, "updated": updated, "errors": errors}


def import_proxies_csv(path: Path) -> dict[str, Any]:
    """Import proxy endpoints from CSV and report duplicate rows as skipped."""
    created, raw_errors = db.import_proxy_csv(path.read_text(encoding="utf-8"))
    skipped = []
    errors = []
    for error in raw_errors:
        if error.get("error") == "duplicate proxy endpoint":
            skipped.append(error)
        else:
            errors.append(error)
    return {"created": created, "skipped": skipped, "errors": errors}
