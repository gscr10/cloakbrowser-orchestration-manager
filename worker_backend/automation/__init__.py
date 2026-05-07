"""Composable automation runtime for Worker business scripts."""

from .errors import AutomationScriptError
from .registry import list_templates, register_template, run_template, unregister_template

__all__ = ["AutomationScriptError", "list_templates", "register_template", "run_template", "unregister_template"]
