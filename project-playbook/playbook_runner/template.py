"""Render ``{{ dotted.path }}`` templates against the applicant data context."""
from __future__ import annotations

import re
from typing import Any

from .context import DataError, resolve_path

_TOKEN = re.compile(r"\{\{\s*(.*?)\s*\}\}")


def render_text(value: Any, context: dict[str, Any]) -> str:
    """Interpolate every ``{{ path }}`` token in a string and return a string.

    Non-string values pass through via ``str()``. A missing path raises, so a
    playbook never silently submits a blank required field.
    """
    if not isinstance(value, str):
        return "" if value is None else str(value)

    def repl(match: re.Match[str]) -> str:
        path = match.group(1)
        resolved = resolve_path(path, context)
        if resolved is None:
            raise DataError(f"template path '{path}' resolved to null")
        return str(resolved)

    return _TOKEN.sub(repl, value)


def resolve_native(expr: str, context: dict[str, Any]) -> Any:
    """Resolve a value to its native type (bool/list/str/...).

    Accepts either a bare path (``a.b.c``) or a single ``{{ a.b.c }}`` token.
    Used for ``pick.source`` where we need the real bool/None, not its text.
    """
    expr = expr.strip()
    match = _TOKEN.fullmatch(expr)
    if match:
        expr = match.group(1).strip()
    return resolve_path(expr, context, default=None)
