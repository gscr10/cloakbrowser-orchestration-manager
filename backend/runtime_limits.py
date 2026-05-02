"""Runtime limits shared by manual launches and the scheduler."""

from __future__ import annotations

import os
from pathlib import Path


MIN_RUNNING_PROFILES = 1
MAX_RUNNING_PROFILES_LIMIT = 15
DEFAULT_RUNNING_PROFILES = "auto"
_MIN_FREE_MEMORY_MB = 512
_MIN_FREE_MEMORY_RATIO = 0.08
_MAX_LOAD_RATIO = 1.5


def _resource_pressure_check_disabled() -> bool:
    raw = os.environ.get("DISABLE_RESOURCE_PRESSURE_CHECK", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def max_running_profiles() -> int:
    """Return the configured per-service running profile limit.

    By default the service uses an adaptive mode: it allows up to the hard cap
    and lets per-launch resource pressure checks decide whether more profiles
    can be started. Operators may still pin a numeric cap with
    MAX_RUNNING_PROFILES=1..15.
    """
    raw = os.environ.get("MAX_RUNNING_PROFILES", DEFAULT_RUNNING_PROFILES).strip().lower()
    if raw in {"", "auto"}:
        return MAX_RUNNING_PROFILES_LIMIT
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError("MAX_RUNNING_PROFILES must be 'auto' or an integer") from exc
    if not MIN_RUNNING_PROFILES <= value <= MAX_RUNNING_PROFILES_LIMIT:
        raise ValueError(
            f"MAX_RUNNING_PROFILES must be between {MIN_RUNNING_PROFILES} "
            f"and {MAX_RUNNING_PROFILES_LIMIT}"
        )
    return value


def launch_block_reason() -> str | None:
    """Return a resource pressure reason when launching should be delayed."""
    if _resource_pressure_check_disabled():
        return None
    memory_reason = _memory_pressure_reason()
    if memory_reason:
        return memory_reason
    return _cpu_pressure_reason()


def _memory_pressure_reason() -> str | None:
    limit_mb = _read_cgroup_memory_limit_mb()
    current_mb = _read_cgroup_memory_current_mb()
    if limit_mb and current_mb is not None:
        available_mb = limit_mb - current_mb
        required_mb = max(_MIN_FREE_MEMORY_MB, int(limit_mb * _MIN_FREE_MEMORY_RATIO))
        if available_mb < required_mb:
            return (
                "Insufficient memory headroom: "
                f"available={available_mb}MB required={required_mb}MB"
            )
        return None

    meminfo = _read_meminfo_mb()
    if meminfo:
        available_mb = meminfo.get("MemAvailable")
        total_mb = meminfo.get("MemTotal")
        if available_mb is not None and total_mb:
            required_mb = max(_MIN_FREE_MEMORY_MB, int(total_mb * _MIN_FREE_MEMORY_RATIO))
            if available_mb < required_mb:
                return (
                    "Insufficient memory headroom: "
                    f"available={available_mb}MB required={required_mb}MB"
                )
    return None


def _cpu_pressure_reason() -> str | None:
    try:
        load_1m = os.getloadavg()[0]
    except (AttributeError, OSError):
        return None
    cpu_count = _read_cgroup_cpu_count() or os.cpu_count() or 1
    if load_1m > cpu_count * _MAX_LOAD_RATIO:
        return (
            "High CPU pressure: "
            f"load_1m={load_1m:.2f} cpu_capacity={cpu_count:.2f}"
        )
    return None


def _read_cgroup_memory_limit_mb() -> int | None:
    for path in (
        Path("/sys/fs/cgroup/memory.max"),
        Path("/sys/fs/cgroup/memory/memory.limit_in_bytes"),
    ):
        value = _read_int_file(path)
        if value and value < 1 << 60:
            return value // (1024 * 1024)
    return None


def _read_cgroup_memory_current_mb() -> int | None:
    for path in (
        Path("/sys/fs/cgroup/memory.current"),
        Path("/sys/fs/cgroup/memory/memory.usage_in_bytes"),
    ):
        value = _read_int_file(path)
        if value is not None:
            return value // (1024 * 1024)
    return None


def _read_cgroup_cpu_count() -> float | None:
    cpu_max = Path("/sys/fs/cgroup/cpu.max")
    try:
        quota, period = cpu_max.read_text().strip().split()[:2]
        if quota != "max":
            return max(float(quota) / float(period), 0.1)
    except (FileNotFoundError, ValueError, ZeroDivisionError):
        pass

    quota = _read_int_file(Path("/sys/fs/cgroup/cpu/cpu.cfs_quota_us"))
    period = _read_int_file(Path("/sys/fs/cgroup/cpu/cpu.cfs_period_us"))
    if quota and period and quota > 0:
        return max(quota / period, 0.1)
    return None


def _read_meminfo_mb() -> dict[str, int]:
    result: dict[str, int] = {}
    try:
        lines = Path("/proc/meminfo").read_text().splitlines()
    except FileNotFoundError:
        return result
    for line in lines:
        key, _, rest = line.partition(":")
        parts = rest.strip().split()
        if parts and parts[0].isdigit():
            result[key] = int(parts[0]) // 1024
    return result


def _read_int_file(path: Path) -> int | None:
    try:
        raw = path.read_text().strip()
    except FileNotFoundError:
        return None
    if raw == "max":
        return None
    try:
        return int(raw)
    except ValueError:
        return None
