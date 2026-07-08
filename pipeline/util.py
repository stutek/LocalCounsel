"""Tiny shared helpers for the LocalCounsel pipeline (no nox import)."""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from .config import BUILD, ROOT


def stamp(dt: datetime) -> str:
    """UTC ISO-8601 timestamp, colon-free so it is filename-portable (Windows-safe)."""
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z").replace(":", "-")


def link_latest(target: Path, link: Path) -> None:
    """Point ``link`` at ``target`` (symlink, copy fallback) for 'latest' convenience."""
    try:
        if link.exists() or link.is_symlink():
            link.unlink()
        link.symlink_to(target.name)  # relative within the same dir
    except OSError:
        shutil.copyfile(target, link)


def safe_remove_dir(session, path: Path) -> None:
    """Wipes a directory only if it passes strict path containment checks.

    ``session`` is duck-typed (needs ``.error`` / ``.log``) so this module stays
    free of a module-level nox import.
    """
    # 1. Resolve paths to absolute paths to prevent symlink tricks
    abs_path = path.resolve()
    abs_root = ROOT.resolve()
    abs_build = BUILD.resolve()

    # 2. Check path containment (must be strictly inside BUILD, which is inside ROOT)
    try:
        abs_path.relative_to(abs_build)
        abs_path.relative_to(abs_root)
    except ValueError:
        session.error(f"Safety Check Failed: Path '{abs_path}' is outside the authorized build directory.")
        return

    # 3. Prevent deleting critical parent directories
    if abs_path in (abs_root, abs_build):
        session.error(f"Safety Check Failed: Attempted to delete critical folder '{abs_path}'.")
        return

    # 4. Folder name specific guard
    if abs_path.name not in ("logs", "reports"):
        session.error(f"Safety Check Failed: Folder name '{abs_path.name}' is not allowed for log cleaning.")
        return

    # If all checks pass, delete it
    if abs_path.exists():
        session.log(f"Removing {abs_path} ...")
        shutil.rmtree(abs_path)
