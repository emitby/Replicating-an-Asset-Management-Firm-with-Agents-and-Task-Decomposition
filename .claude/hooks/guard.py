"""Claude Code PreToolUse hook: no deleting files, no access outside this project.

Registered in .claude/settings.json for the Bash, Read, Write, Edit, MultiEdit,
NotebookEdit, Glob and Grep tools. Claude Code sends the pending tool call as
JSON on stdin; this script exits with code 2 and a reason on stderr to block
it (Claude sees the reason and can adjust), or 0 to allow it.

Rules (CLAUDE.md guardrails):
- Bash commands may not delete: rm, rmdir, del, erase, rd, unlink, shred,
  Remove-Item, ``find -delete``, ``git rm`` and ``git clean`` are blocked.
- Any path a tool would touch must resolve inside the project folder. For Bash,
  every argument that looks like a path (absolute, ``~``, Git Bash ``/c/...``,
  or containing ``..``) is checked; ``/dev/null`` is allowed.

Standalone on purpose (no project imports, no ``os``), so it works even when
the project's code is broken.
"""

import json
import re
import shlex
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
DELETE_RE = re.compile(
    r"(^|[;&|`(]|\$\()\s*(sudo\s+)?(rm|rmdir|del|erase|rd|unlink|shred)(\s|$)"
    r"|Remove-Item|\bfind\b[^;&|]*\s-delete\b|\bgit\s+(rm|clean)\b",
    re.IGNORECASE | re.MULTILINE)
PATH_TOOLS = {"Read": "file_path", "Write": "file_path", "Edit": "file_path", "MultiEdit": "file_path",
              "NotebookEdit": "notebook_path", "Glob": "path", "Grep": "path"}
ALLOWED_OUTSIDE = {"/dev/null", "nul"}


def _resolve(raw):
    """Resolve a path argument the way the shell would (Git Bash /c/... -> C:/...), relative to the project."""
    s = raw.strip().strip("'\"")
    m = re.match(r"^/([a-zA-Z])(/.*)?$", s)
    if m and len(s) > 1:
        s = f"{m.group(1)}:{m.group(2) or '/'}"
    if s.startswith("~"):
        s = str(Path.home()) + s[1:]
    p = Path(s)
    return (p if p.is_absolute() else PROJECT / p).resolve()


def _inside(raw):
    """True if the path is inside the project (or is an allowed device like /dev/null)."""
    if raw.strip().strip("'\"").lower() in ALLOWED_OUTSIDE:
        return True
    try:
        target = _resolve(raw)
    except (OSError, ValueError):
        return False
    return target == PROJECT or target.is_relative_to(PROJECT)


def _path_like(token):
    """An argument that names a filesystem location outside the current folder, by its shape."""
    return bool(re.match(r"^(/|~|[A-Za-z]:[\\/]|\\\\)", token)) or bool(re.search(r"(^|[\\/])\.\.([\\/]|$)", token))


def check(tool, tool_input):
    """Return a reason to block the tool call, or None to allow it."""
    if tool == "Bash":
        cmd = tool_input.get("command", "")
        if DELETE_RE.search(cmd):
            return "Deleting files is forbidden in this project (CLAUDE.md)."
        try:
            tokens = shlex.split(cmd, posix=True)
        except ValueError:
            tokens = cmd.split()
        for tok in tokens:
            # "--out=/x" and ">/x" name a path after the "=" or the redirect.
            part = tok.rsplit("=", 1)[-1].lstrip("<>")
            if _path_like(part) and not part.startswith("//") and not _inside(part):
                return f"Access outside the project folder is forbidden: {part}"
        return None
    key = PATH_TOOLS.get(tool)
    if key and tool_input.get(key) and not _inside(tool_input[key]):
        return f"Access outside the project folder is forbidden: {tool_input[key]}"
    return None


def main():
    """Read the hook payload from stdin; exit 2 with a reason to block, 0 to allow."""
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return 0
    reason = check(payload.get("tool_name", ""), payload.get("tool_input") or {})
    if reason:
        print(reason, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
