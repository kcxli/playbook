"""Private filesystem helpers for run artifacts that may contain applicant data."""

from __future__ import annotations

import os
from pathlib import Path


def ensure_private_dir(path: str | Path) -> Path:
    directory = Path(path)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        directory.chmod(0o700)
    except OSError:
        pass
    return directory


def write_private_text(path: str | Path, text: str) -> Path:
    target = Path(path)
    ensure_private_dir(target.parent)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(target, flags, 0o600)
    _make_fd_private(fd)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)
    _make_private(target)
    return target


def append_private_text(path: str | Path, text: str) -> Path:
    target = Path(path)
    ensure_private_dir(target.parent)
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(target, flags, 0o600)
    _make_fd_private(fd)
    with os.fdopen(fd, "a", encoding="utf-8") as handle:
        handle.write(text)
    _make_private(target)
    return target


def make_private(path: str | Path) -> None:
    _make_private(Path(path))


def _make_private(path: Path) -> None:
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _make_fd_private(fd: int) -> None:
    try:
        os.fchmod(fd, 0o600)
    except OSError:
        pass
