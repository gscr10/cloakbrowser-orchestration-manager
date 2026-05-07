"""Compatibility wrapper for the composable automation package."""

from __future__ import annotations

from .automation import AutomationScriptError, list_templates, run_template

__all__ = ["AutomationScriptError", "list_templates", "run_template"]
