from __future__ import annotations


class AutomationScriptError(RuntimeError):
    """Script failure that still carries structured result/artifact data."""

    def __init__(self, message: str, result: dict | None = None) -> None:
        super().__init__(message)
        self.result = result or {}
