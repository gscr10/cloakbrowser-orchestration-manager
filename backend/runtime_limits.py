"""Runtime limits shared by manual launches and the scheduler."""

from __future__ import annotations

import os


MIN_RUNNING_PROFILES = 1
MAX_RUNNING_PROFILES_LIMIT = 15
DEFAULT_RUNNING_PROFILES = 15


def max_running_profiles() -> int:
    """Return the configured per-service running profile limit.

    The service is intended to run independently on each Linux host. Keep the
    local cap bounded so a bad environment value cannot accidentally fan out an
    excessive number of Chromium and Xvnc processes.
    """
    raw = os.environ.get("MAX_RUNNING_PROFILES", str(DEFAULT_RUNNING_PROFILES))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError("MAX_RUNNING_PROFILES must be an integer") from exc
    if not MIN_RUNNING_PROFILES <= value <= MAX_RUNNING_PROFILES_LIMIT:
        raise ValueError(
            f"MAX_RUNNING_PROFILES must be between {MIN_RUNNING_PROFILES} "
            f"and {MAX_RUNNING_PROFILES_LIMIT}"
        )
    return value