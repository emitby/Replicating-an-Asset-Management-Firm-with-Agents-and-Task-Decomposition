"""Process-level file sandbox: a Python audit hook (PEP 578) that enforces CLAUDE.md's guardrails.

The runtime hooks in `strategy.hooks` check what agents *ask* tools to do. This
module checks what the Python process *does*, whatever code (ours or a
library's) asks for it:

- **No deletion.** ``os.remove``/``os.unlink``, ``os.rmdir`` and ``shutil.rmtree``
  raise `SandboxViolation`. One documented exception: the project's ``.cache/``
  folder, where libraries keep scratch files (matplotlib, for example, removes
  its own lock file after building its font cache).
- **No writes outside the project.** Opening a file for writing, creating a
  directory, or renaming/replacing a file outside the project directory raises.
- **No reads outside the project.** Opening a file for reading outside the
  project raises, except under the Python installation (``sys.base_prefix``,
  ``sys.exec_prefix``), which imports need.

An audit hook cannot be removed once installed, so `install` is called once,
by the command line, and the tests exercise it in a subprocess. Every blocked
event is also appended to `VIOLATIONS` for reporting.
"""

import sys
from pathlib import Path

from strategy.paths import CACHE_DIR, PROJECT_DIR, _strip_extended_prefix

DELETE_EVENTS = {"os.remove", "os.rmdir", "shutil.rmtree"}
WRITE_FLAGS = 0x0001 | 0x0002 | 0x0040 | 0x0200 | 0x0400   # O_WRONLY | O_RDWR | O_CREAT | O_TRUNC | O_APPEND
VIOLATIONS = []
_installed = False


class SandboxViolation(PermissionError):
    """Raised by the audit hook when code tries a forbidden file operation."""


def _resolve(path):
    """Absolute, normalized form of a path argument from an audit event (``None`` for file descriptors)."""
    if isinstance(path, int) or path is None:
        return None
    if isinstance(path, bytes):
        path = path.decode(errors="replace")
    try:
        return _strip_extended_prefix(Path(path).resolve())
    except (OSError, ValueError, TypeError):
        return Path(str(path))


def _inside(path, *roots):
    """True if `path` is inside any of `roots`."""
    return any(path == r or path.is_relative_to(r) for r in roots)


def _is_write(mode, flags):
    """True if an ``open`` audit event asks for write access (by mode string or os.open flags)."""
    if isinstance(mode, str) and any(c in mode for c in "wax+"):
        return True
    return isinstance(flags, int) and bool(flags & WRITE_FLAGS)


def check_event(event, args, project=PROJECT_DIR, cache=CACHE_DIR, read_roots=None):
    """Decide whether one audit event is allowed.

    Args:
        event: the audit event name (e.g. ``"open"``, ``"os.remove"``).
        args: the event's arguments.
        project: the only directory that may be written.
        cache: the only directory in which deletion is allowed (library scratch files).
        read_roots: extra directories that may be read (default: the Python installation).

    Returns:
        A reason string if the event must be blocked, else ``None``.
    """
    read_roots = read_roots or (_resolve(sys.base_prefix), _resolve(sys.exec_prefix))
    project, cache = _resolve(project), _resolve(cache)
    if event in DELETE_EVENTS:
        target = _resolve(args[0]) if args else None
        if target is not None and _inside(target, cache):
            return None
        return f"deleting {target} is forbidden"
    if event == "open":
        path, mode, flags = (list(args) + [None, None, None])[:3]
        target = _resolve(path)
        if target is None:
            return None
        if _is_write(mode, flags):
            return None if _inside(target, project) else f"writing {target} outside the project is forbidden"
        return None if _inside(target, project, *read_roots) else f"reading {target} outside the project is forbidden"
    if event in ("os.rename", "os.replace"):
        for p in args[:2]:
            target = _resolve(p)
            if target is not None and not _inside(target, project):
                return f"moving files outside the project ({target}) is forbidden"
    if event == "os.mkdir":
        target = _resolve(args[0]) if args else None
        if target is not None and not _inside(target, project):
            return f"creating {target} outside the project is forbidden"
    return None


def _hook(event, args):
    """The installed audit hook: raise `SandboxViolation` on a forbidden event."""
    if event not in ("open", "os.rename", "os.replace", "os.mkdir", *DELETE_EVENTS):
        return
    reason = check_event(event, args)
    if reason:
        VIOLATIONS.append({"event": event, "reason": reason})
        raise SandboxViolation(f"Sandbox: {reason}.")


def install():
    """Install the audit hook for the rest of this process (idempotent; cannot be undone).

    Side effects:
        Every later file open, delete, rename and mkdir in this process is checked.
    """
    global _installed
    if not _installed:
        sys.addaudithook(_hook)
        _installed = True
