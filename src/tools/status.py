"""What needs attention: a Markdown report on the data's upkeep.

Usage:
  python src/tools/status.py [--check-links] [--today YYYY-MM-DD] [--stale-days 30]

Reports, for every election that hasn't happened yet:
  - facts and mappings still unverified, and facts the owner can't verify yet (no archive_url);
  - races where nobody's incumbent status is known, or no candidate has money information;
  - "who holds this office" checks older than --stale-days.
With --check-links it also requests every cited source and lists the ones that fail (slow).
It only reads; it never edits data.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from collections import Counter
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import GENERATED, REPO, all_facts, fetch  # noqa: E402


def upcoming_races(root: Path, today: str) -> list[tuple[str, dict, list[dict]]]:
    out = []
    for f in sorted((root / "data/states").rglob("race.yaml")):
        race = yaml.safe_load(f.read_text(encoding="utf-8"))
        if str(race.get("election_date")) < today:
            continue
        cands = [yaml.safe_load(c.read_text(encoding="utf-8")) for c in sorted((f.parent / "candidates").glob("*.yaml"))]
        out.append((f.parent.relative_to(root / "data/states").as_posix(), race, cands))
    return out


def report(root: Path, today: str, stale_days: int, check_links: bool = False, fetcher=fetch) -> str:
    facts = list(all_facts(root))
    by_status = Counter(f.get("verification") for _p, _t, f in facts)
    no_archive = [(p, f) for p, _t, f in facts if not f.get("archive_url")]
    bulk = [(p, f) for p, f in no_archive if str(f.get("source_url", "")).lower().split("?")[0].endswith(".zip")]
    generated = [(p, f) for p, f in no_archive if p.name in GENERATED]
    to_archive = len(no_archive) - len(bulk) - len(generated)
    mappings = Counter()
    for f in (root / "data/states").rglob("candidates/*.yaml"):
        for m in yaml.safe_load(f.read_text(encoding="utf-8")).get("mappings") or []:
            mappings[m.get("verification")] += 1

    races = upcoming_races(root, today)
    unknown = [p for p, _r, cs in races if cs and all(c.get("incumbent") is None for c in cs)]
    no_money = [p for p, r, cs in races
                if cs and not any(c.get("funding") for c in cs)
                and not any(s["id"].endswith("#S-FUND") for s in r.get("sources") or [])]
    cutoff = (dt.date.fromisoformat(today) - dt.timedelta(days=stale_days)).isoformat()
    stale = [p for p, r, _cs in races for s in r.get("sources") or []
             if s["id"].endswith("#S-HOLDER") and str(s.get("retrieved") or "") < cutoff]

    lines = [f"# Upkeep report, {today}", "",
             "## Verification",
             f"- Facts: {len(facts)} ({by_status.get('verified', 0)} verified, {by_status.get('unverified', 0)} unverified)",
             f"- Mappings: {sum(mappings.values())} ({mappings.get('verified', 0)} verified)",
             f"- No archived copy yet: {to_archive}" + (" — run `python src/tools/archive.py`" if to_archive else ""),
             f"- Bulk-data sources too large to archive (verify against the agency's own search): {len(bulk)}",
             f"- In collector-generated files (add the archive in the collector, then regenerate): {len(generated)}", "",
             f"## Upcoming races ({len(races)})",
             f"- Nobody's incumbent status known: {len(unknown)}",
             f"- No money information for any candidate: {len(no_money)}",
             f"- \"Who holds this office\" checked more than {stale_days} days ago: {len(stale)}"
             + (" — run `python src/tools/check_rosters.py`" if stale else "")]
    for title, items in (("Incumbent status unknown", unknown), ("No money information", no_money)):
        if items:
            lines += ["", f"<details><summary>{title} ({len(items)})</summary>", ""]
            lines += [f"- `{p}`" for p in items] + ["", "</details>"]

    if check_links:
        urls = sorted({f["source_url"] for _p, _t, f in facts if str(f.get("source_url", "")).startswith("http")})
        broken = []
        for url in urls:
            if url.lower().split("?")[0].endswith(".zip"):
                continue  # bulk downloads: too big to fetch weekly
            try:
                fetcher(url, tries=2, wait=5.0, timeout=60.0)
            except RuntimeError as err:
                broken.append(f"- {url} ({str(err).split(': ', 1)[-1][:80]})")
        lines += ["", f"## Source links ({len(urls)} checked)",
                  f"- Not loading: {len(broken)}" + (" — the archived copy still holds the record" if broken else "")]
        lines += broken
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=REPO)
    parser.add_argument("--today", default=dt.date.today().isoformat())
    parser.add_argument("--stale-days", type=int, default=30)
    parser.add_argument("--check-links", action="store_true")
    args = parser.parse_args(argv)
    sys.stdout.write(report(args.root, args.today, args.stale_days, args.check_links))
    return 0


if __name__ == "__main__":
    sys.exit(main())
