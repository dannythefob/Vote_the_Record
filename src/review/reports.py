"""Read "Report a problem" submissions stored by the Worker (src/worker/index.js).

Usage:  python src/review/reports.py                 (list every report, oldest first)
        python src/review/reports.py --done KEY      (delete one report after handling it)

Only the owner runs this. It uses Wrangler, so log in once with `npx wrangler login`.
Reports are private: never commit or publish them. If a report leads to a change, make
the change and add an entry to corrections/log.yaml by hand (CLAUDE.md rule 8).
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys

BINDING = "REPORTS"
FIELDS = (("item", "Item"), ("problem", "Problem"), ("source", "Source"), ("contact", "Contact"))


def wrangler(*args: str) -> str:
    npx = shutil.which("npx")
    if not npx:
        raise SystemExit("npx not found: install Node.js first.")
    cmd = [npx, "--yes", "wrangler", "kv", "key", *args, "--binding", BINDING, "--remote"]
    done = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if done.returncode != 0:
        raise SystemExit(f"wrangler failed:\n{done.stderr.strip() or done.stdout.strip()}")
    return done.stdout


def list_keys(run=wrangler) -> list[str]:
    """Report keys, oldest first (keys start with the time the report arrived)."""
    return sorted(k["name"] for k in json.loads(run("list", "--prefix", "report:")))


def format_report(key: str, raw: str) -> str:
    report = json.loads(raw)
    lines = [f"== {key}", f"Received: {report.get('received', '?')}"]
    for field, label in FIELDS:
        value = report.get(field) or "(none)"
        lines.append(f"{label}: {value}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--done", metavar="KEY", help="delete this report once you have handled it")
    args = parser.parse_args(argv)
    if args.done:
        if not args.done.startswith("report:"):
            raise SystemExit("Not a report key (keys start with 'report:').")
        wrangler("delete", args.done)
        print(f"Deleted {args.done}")
        return 0
    keys = list_keys()
    if not keys:
        print("No reports.")
        return 0
    for key in keys:
        print(format_report(key, wrangler("get", key, "--text")))
        print()
    print(f"{len(keys)} report(s). After handling one: python src/review/reports.py --done KEY")
    return 0


if __name__ == "__main__":
    sys.exit(main())
