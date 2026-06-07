"""Applicant data context: load profile JSON, expose builtins, resolve dotted paths."""
from __future__ import annotations

import json
import random
import string
from datetime import date, datetime
from pathlib import Path
from typing import Any


class DataError(Exception):
    """Raised when applicant data cannot be loaded or a path cannot be resolved."""


_MISSING = object()


def _make_builtins() -> dict[str, str]:
    """Values supplied by the runner, refreshed on every run.

    ``unique`` is a short run-stamp (date + time + random tail) suitable for
    making account usernames / emails collision-free across re-runs.
    """
    now = datetime.now()
    tail = "".join(random.choices(string.ascii_lowercase + string.digits, k=4))
    return {
        "today": now.strftime("%m/%d/%Y"),
        "today_iso": date.today().isoformat(),
        "year": now.strftime("%Y"),
        "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
        "unique": now.strftime("%Y%m%d%H%M%S") + tail,
        "run_id": now.strftime("%Y%m%d%H%M%S") + tail,
    }


def load_context(data_paths: list[str]) -> dict[str, Any]:
    """Merge one or more JSON data files, attach builtins, and refresh templates.

    Later files override earlier ones (shallow top-level merge). The reserved
    ``builtins`` namespace is always added last and cannot be shadowed.

    Any ``{{ ... }}`` token *inside the data* is expanded at load time so a
    profile can self-refresh — e.g. ``"user_name": "jdoe_{{ builtins.unique }}"``
    yields a fresh, collision-free username on every run.
    """
    context: dict[str, Any] = {}
    for raw in data_paths:
        path = Path(raw)
        if not path.exists():
            raise DataError(f"data file not found: {path}")
        try:
            loaded = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            raise DataError(f"invalid JSON in {path}: {exc}") from exc
        if not isinstance(loaded, dict):
            raise DataError(f"data file {path} must contain a JSON object at the top level")
        context.update(loaded)

    context["builtins"] = _make_builtins()
    _refresh_in_place(context)
    return context


def _refresh_in_place(context: dict[str, Any]) -> None:
    """Expand ``{{ ... }}`` tokens found in the data against the context.

    Done as a single pass over everything except the ``builtins`` namespace.
    Imported locally to avoid a circular import with :mod:`template`.
    """
    from .template import render_text

    def expand(node: Any) -> Any:
        if isinstance(node, str):
            return render_text(node, context) if "{{" in node else node
        if isinstance(node, dict):
            return {k: expand(v) for k, v in node.items()}
        if isinstance(node, list):
            return [expand(v) for v in node]
        return node

    for key in list(context.keys()):
        if key == "builtins":
            continue
        context[key] = expand(context[key])


def resolve_path(path: str, context: dict[str, Any], default: Any = _MISSING) -> Any:
    """Resolve a dotted path like ``a.b.0.c`` against the context.

    List indices are written as integers in the path (``schools.0.degree``).
    Returns ``default`` if provided and the path is missing; otherwise raises.
    """
    current: Any = context
    parts = [p for p in path.strip().split(".") if p != ""]
    if not parts:
        raise DataError("empty data path")

    for part in parts:
        if isinstance(current, dict):
            if part not in current:
                return _missing(path, default)
            current = current[part]
        elif isinstance(current, (list, tuple)):
            if not part.lstrip("-").isdigit():
                return _missing(path, default)
            idx = int(part)
            if idx >= len(current) or idx < -len(current):
                return _missing(path, default)
            current = current[idx]
        else:
            return _missing(path, default)
    return current


def _missing(path: str, default: Any) -> Any:
    if default is _MISSING:
        raise DataError(f"data path not found: '{path}'")
    return default


def path_exists(path: str, context: dict[str, Any]) -> bool:
    sentinel = object()
    return resolve_path(path, context, default=sentinel) is not sentinel
