"""Re-check who holds each office against the official rosters already cited in the data.

Usage:
  python src/tools/check_rosters.py [--ballot <ballot.yaml>]

Every race with a "Who holds this office now" fact (#S-HOLDER) names its official roster in
that fact's source_url. This fetches each roster (3 tries), looks for every candidate's name on
it, and compares with the candidates' `incumbent` values. It only reports; it never edits data.
A change means someone should look: a seat may have changed hands, or the page may have moved.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import REPO, fetch, name_on_page, page_text  # noqa: E402


def races_with_holder(root: Path, ballot: Path | None) -> list[tuple[str, dict, dict]]:
    if ballot:
        paths = [p for p in yaml.safe_load(ballot.read_text(encoding="utf-8"))["contests"]]
        files = [root / "data/states" / p / "race.yaml" for p in paths]
    else:
        files = sorted((root / "data/states").rglob("race.yaml"))
    out = []
    for f in files:
        if not f.exists():
            continue
        race = yaml.safe_load(f.read_text(encoding="utf-8"))
        holder = next((s for s in race.get("sources") or [] if s["id"].endswith("#S-HOLDER")), None)
        if holder:
            out.append((f.parent.relative_to(root / "data/states").as_posix(), race, holder))
    return out


KNOWN = Path(__file__).resolve().parent / "roster_known.yaml"


def known(path: Path = KNOWN) -> set[tuple[str, str]]:
    """Reviewed findings to stop repeating: (race path, candidate file stem)."""
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else None
    return {(k["race"], k["candidate"]) for k in (doc or {}).get("known") or []}


def check(root: Path, ballot: Path | None, fetcher=fetch, known_set: set | None = None) -> list[str]:
    pages: dict[str, str | None] = {}
    lines = []
    skip = known() if known_set is None else known_set
    for race_path, race, holder in races_with_holder(root, ballot):
        url = holder["source_url"]
        if url not in pages:
            try:
                pages[url] = page_text(fetcher(url))
            except RuntimeError as err:
                pages[url] = None
                lines.append(f"FETCH FAILED {url}: {err}")
        text = pages[url]
        if text is None:
            continue
        for f in sorted((root / "data/states" / race_path / "candidates").glob("*.yaml")):
            cand = yaml.safe_load(f.read_text(encoding="utf-8"))
            if (race_path, f.stem) in skip:
                continue
            listed = name_on_page(cand["name"], text)
            if cand.get("incumbent") is True and not listed:
                lines.append(f"CHECK {race_path}: {cand['name']} is marked incumbent but isn't found on {url}")
            elif cand.get("incumbent") is False and listed:
                lines.append(f"CHECK {race_path}: {cand['name']} now appears on {url} "
                             "(a new officeholder, or holding a different seat on the same list)")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ballot", type=Path)
    parser.add_argument("--root", type=Path, default=REPO)
    args = parser.parse_args(argv)
    lines = check(args.root, args.ballot)
    print("\n".join(lines) if lines else "Rosters: no changes found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
