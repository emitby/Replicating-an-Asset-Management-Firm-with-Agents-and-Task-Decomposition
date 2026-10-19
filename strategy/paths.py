"""Filesystem confinement. Every read and write in this project goes through here.

Guardrail (CLAUDE.md): nothing outside the project directory is read or
modified, and no files are deleted. There is no `os` import anywhere in the
project; pathlib covers what we need.
"""

import json
from datetime import datetime
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
RUNS_DIR = PROJECT_DIR / "runs"
DATA_CACHE_DIR = PROJECT_DIR / "data"
CACHE_DIR = PROJECT_DIR / ".cache"


class ConfinementError(PermissionError):
    pass


def confine(path):
    """Resolve `path` (relative paths are taken from the project root) and refuse
    anything outside the project directory."""
    p = Path(path)
    resolved = _strip_extended_prefix((p if p.is_absolute() else PROJECT_DIR / p).resolve())
    if not resolved.is_relative_to(PROJECT_DIR):
        raise ConfinementError(f"Refusing to touch {resolved}: outside the project directory.")
    return resolved


def _strip_extended_prefix(path):
    """On Windows, resolve() can return '\\\\?\\C:\\...' (e.g. while a directory is being created
    concurrently). Normalize it, or the confinement check would reject valid paths."""
    s = str(path)
    if s.startswith("\\\\?\\") and not s.startswith("\\\\?\\UNC\\"):
        return Path(s[4:])
    return path


def new_run_dir(label=None):
    """Create a fresh, never-reused run directory under runs/."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = f"{stamp}-{label}" if label else stamp
    for i in range(1000):
        candidate = confine(RUNS_DIR / (base if i == 0 else f"{base}-{i}"))
        if not candidate.exists():
            candidate.mkdir(parents=True)
            return candidate
    raise ConfinementError("Could not allocate a run directory.")


def write_text(path, text):
    path = confine(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
    return path


def write_json(path, obj):
    return write_text(path, json.dumps(obj, indent=2, default=_json_default))


def read_json(path):
    return json.loads(confine(path).read_text(encoding="utf-8"))


def _json_default(o):
    if hasattr(o, "isoformat"):
        return o.isoformat()
    if hasattr(o, "item"):          # numpy scalars
        return o.item()
    raise TypeError(f"Not JSON serializable: {type(o).__name__}")
