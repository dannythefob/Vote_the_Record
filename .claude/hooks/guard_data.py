"""PreToolUse hook: require the owner's approval for anything touching data/.

Returns permissionDecision "ask" (which prompts even in auto mode) when:
- Edit/Write/NotebookEdit targets a path under <repo>/data/
- a Bash/PowerShell command mentions a data/ path or changes into data

Anything else passes through silently. See CLAUDE.md rule 3a.
"""

import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.path.normcase(os.path.join(REPO, "data"))

# data/ or data\ as a path segment (not metadata/), or cd/pushd/Set-Location into data.
SHELL_DATA = re.compile(
    r"(?<![\w.-])data[\\/]|\b(cd|pushd|set-location|sl)\s+[\"']?(\.[\\/])?data\b",
    re.IGNORECASE,
)


def under_data(path, cwd):
    full = os.path.normcase(os.path.abspath(os.path.join(cwd or REPO, path)))
    return full == DATA or full.startswith(DATA + os.sep)


def main():
    event = json.load(sys.stdin)
    tool = event.get("tool_name", "")
    args = event.get("tool_input") or {}
    cwd = event.get("cwd")

    hit = False
    if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        path = args.get("file_path") or args.get("notebook_path")
        hit = bool(path) and under_data(path, cwd)
    elif tool in ("Bash", "PowerShell"):
        hit = bool(SHELL_DATA.search(args.get("command", "")))

    if hit:
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "ask",
                "permissionDecisionReason": "Changes under data/ need the project owner's approval (CLAUDE.md rule 3a).",
            }
        }))


if __name__ == "__main__":
    main()
