"""Load a validated data repo into plain dicts for the templates.

The validator has already checked every file, so this module only reads and
arranges: it never repairs or guesses at data.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "validate"))
from validate import _NoDateLoader, classify  # noqa: E402

STATE_NAMES = {"TX": "Texas"}


def load_yaml(path: Path):
    return yaml.load(path.read_text(encoding="utf-8"), Loader=_NoDateLoader)


def title_from_slug(slug: str) -> str:
    return " ".join(word.capitalize() for word in slug.split("-"))


def load_docs(root: Path) -> dict[str, tuple[str, object]]:
    docs = {}
    for base in ("data", "offices", "corrections"):
        for file in sorted((root / base).rglob("*.yaml")):
            rel = file.relative_to(root).as_posix()
            kind = classify(rel)
            if kind:
                docs[rel] = (kind, load_yaml(file))
    return docs


def race_location(rel: str) -> dict:
    """data/states/tx/localities/harris-county/elections/2026-11-03/x/race.yaml -> parts."""
    parts = rel.split("/")
    state = parts[2]
    if parts[3] == "statewide":
        locality, date, slug = "statewide", parts[5], parts[6]
    else:
        locality, date, slug = parts[4], parts[6], parts[7]
    return {"state": state, "locality": locality, "election_date": date, "slug": slug}


def load_site(root: Path, today: str) -> dict:
    docs = load_docs(root)

    races = []
    for rel, (kind, doc) in docs.items():
        if kind != "race":
            continue
        loc = race_location(rel)
        races.append({
            **loc,
            "name": doc["name"],
            "office_type": doc["office_type"],
            "state_name": STATE_NAMES.get(loc["state"].upper(), loc["state"].upper()),
            "locality_name": "Statewide" if loc["locality"] == "statewide" else title_from_slug(loc["locality"]),
            "url": f"/races/{loc['state']}/{loc['locality']}/{loc['election_date']}/{loc['slug']}/",
            "rel": rel,
        })
    races.sort(key=lambda r: (r["state"], r["locality"] != "statewide", r["locality_name"],
                              r["election_date"], r["name"].casefold()))

    essentials = []
    for rel, (kind, doc) in docs.items():
        if kind != "voter_essentials" or doc["election_date"] < today:
            continue
        items = sorted(doc["items"], key=lambda i: i.get("date") or i.get("start"))
        essentials.append({
            "state": doc["state"],
            "state_name": STATE_NAMES.get(doc["state"], doc["state"]),
            "election_date": doc["election_date"],
            "entries": items,
        })
    essentials.sort(key=lambda e: (e["election_date"], e["state"]))

    corrections = docs.get("corrections/log.yaml", (None, []))[1] or []
    corrections = sorted(corrections, key=lambda c: c["date"], reverse=True)

    facts = fact_index(docs)
    for race in races:
        race.update(assemble_race(docs, race, facts))

    return {"races": races, "essentials": essentials, "corrections": corrections}


FACT_SECTIONS = ("summary", "records", "funding", "endorsements")
RUNNING_ON = ("policy_proposals", "attack_messaging", "contested_claims")


def fact_index(docs: dict) -> dict[str, dict]:
    """Every fact in the repo by ID, so promises and contradictions can link across files."""
    index = {}
    for kind, doc in docs.values():
        if kind == "actions":
            index.update((f["id"], f) for f in doc.get("facts") or [])
        elif kind == "candidate":
            for section in FACT_SECTIONS:
                index.update((f["id"], f) for f in doc.get(section) or [])
            for section in RUNNING_ON:
                index.update((f["id"], f) for f in (doc.get("running_on") or {}).get(section) or [])
    return index


def short(fact: dict) -> str:
    """The fact's headline if it has one, else its full statement."""
    return fact.get("headline") or fact["statement"]


def clip(text: str, limit: int = 110) -> str:
    """Shorten at a word boundary for the at-a-glance card; the full text stays in the details."""
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(",;:-")
    return cut + "…"


def card_text(fact: dict) -> str:
    """Card line: the headline, or else the statement shortened (never reworded)."""
    return fact.get("headline") or clip(fact["statement"])


def topic(fact: dict) -> str:
    """Short topic for the Priorities line, taken from wording already in the fact.

    'Affordability: stop tax increases' (headline) -> 'Affordability'
    'Campaign platform, Flood Protection: ...' (statement) -> 'Flood Protection'
    """
    head = fact.get("headline")
    if head and ":" in head:
        return head.split(":", 1)[0].strip()
    m = re.match(r"Campaign platform, ([^:]{1,40}):", fact["statement"])
    return m.group(1).strip() if m else clip(short(fact), 40)


def glance(cand: dict) -> list[dict]:
    """At-a-glance lines for a candidate card, built only from facts already on file.

    Each line links to the fact(s) it came from, so nothing on the card lacks a source.
    """
    lines = []
    for fact in cand.get("summary") or []:
        lines.append({"icon": "info", "text": card_text(fact), "facts": [fact]})
    for fact in cand.get("funding") or []:
        lines.append({"icon": "money", "text": card_text(fact), "facts": [fact]})
    proposals = (cand.get("running_on") or {}).get("policy_proposals") or []
    if proposals:
        lines.append({"icon": "target", "label": "Priorities",
                      "text": " · ".join(topic(f) for f in proposals), "facts": proposals})
    endorsements = cand.get("endorsements") or []
    if endorsements:
        lines.append({"icon": "megaphone", "label": "Endorsed by",
                      "text": " · ".join(card_text(f) for f in endorsements), "facts": endorsements})
    return lines


RECORD_ON_CARD = 3


def record_top(cand: dict, facts: dict) -> dict:
    """The record block that leads each card: most recent actions first, with results.

    Every item is a fact on file; follow-ups are resolved to their own sourced facts.
    """
    records = sorted(cand.get("records") or [], key=lambda r: r.get("event_date") or "", reverse=True)
    items = []
    for r in records[:RECORD_ON_CARD]:
        items.append({
            "fact": r,
            "kind": r["record_type"],
            "text": card_text(r),
            "year": (r.get("event_date") or "")[:4],
            "result": r.get("result"),
            "followups": [facts[f] for f in r.get("followups") or [] if f in facts],
        })
    return {"items": items, "total": len(records), "more": max(0, len(records) - RECORD_ON_CARD),
            "summary": record_count_text(records)}


RECORD_WORDS = {"vote": ("vote", "votes"), "sponsored": ("measure sponsored", "measures sponsored"),
                "promise_kept": ("promise kept", "promises kept"),
                "promise_broken": ("promise broken", "promises broken"),
                "statement": ("statement", "statements")}


def record_count_text(records: list[dict]) -> str:
    """'2 votes, 1 statement on record' or 'No record on file yet'."""
    if not records:
        return "No record on file yet"
    counts: dict[str, int] = {}
    for r in records:
        counts[r["record_type"]] = counts.get(r["record_type"], 0) + 1
    parts = [f"{n} {RECORD_WORDS[t][0 if n == 1 else 1]}" for t, n in counts.items()]
    return ", ".join(parts) + " on record"


def pick_why_it_matters(race_doc: dict, locality_doc: dict | None, office_doc: dict | None) -> list:
    """The most specific level wins: race, then locality, then office type."""
    for doc in (race_doc, locality_doc, office_doc):
        if doc and doc.get("why_it_matters"):
            return doc["why_it_matters"]
    return []


def assemble_race(docs: dict, race: dict, facts: dict) -> dict:
    office = race["office_type"]
    race_doc = docs[race["rel"]][1]
    office_doc = docs.get(f"offices/{office}/powers.yaml", (None, None))[1]
    survey_doc = docs.get(f"offices/{office}/survey.yaml", (None, None))[1] or {}
    override_doc = docs.get(f"data/states/{race['state']}/office-overrides/{office}.yaml", (None, None))[1]
    locality_doc = None
    if race["locality"] != "statewide":
        locality_doc = docs.get(
            f"data/states/{race['state']}/localities/{race['locality']}/locality.yaml", (None, None))[1]

    race_dir = race["rel"].rsplit("/", 1)[0]
    candidates = [doc for rel, (kind, doc) in docs.items()
                  if kind == "candidate" and rel.startswith(race_dir + "/candidates/")]
    candidates.sort(key=lambda c: (c["name"].casefold(), c["name"]))
    cand_dir = race_dir + "/candidates"
    for cand in candidates:
        cand.setdefault("summary", [])
        cand["glance"] = glance(cand)
        cand["record_top"] = record_top(cand, facts)
        cand["initials"] = "".join(w[0] for w in cand["name"].split()[:2]).upper()
        photo = cand.get("photo")
        cand["photo_src"] = f"/media/{cand_dir.removeprefix('data/')}/{photo['file']}" if photo else None
        cand["photo_path"] = f"{cand_dir}/{photo['file']}" if photo else None
        cand["promises"] = [
            {**entry, "promise_fact": facts.get(entry["promise"]),
             "evidence_facts": [facts.get(e) for e in entry.get("evidence") or []]}
            for entry in cand.get("promise_tracker") or []
        ]

    questions = [
        {"id": f"{office}/{s['id']}", "text": s["scenario"], "powers": s["powers"],
         "options": [{"id": o["id"], "text": o["text"]} for o in s["options"]]}
        for s in survey_doc.get("scenarios") or []
    ]
    payload = {
        "race": race["name"],
        "questions": [{k: q[k] for k in ("id", "text", "options")} for q in questions],
        "candidates": [
            {
                "id": c["id"],
                "name": c["name"],
                "records": [
                    {k: r.get(k) for k in ("id", "record_type", "statement", "label", "claim_status",
                                           "verification", "same_event", "source_url", "source_title")}
                    for r in c.get("records") or []
                ],
                "mappings": [
                    {k: m[k] for k in ("record", "question", "options", "rationale", "verification")}
                    for m in c.get("mappings") or []
                ],
            }
            for c in candidates
        ],
    }
    plain = (override_doc or {}).get("plain_summary") or (office_doc or {}).get("plain_summary")
    return {
        "plain_summary": plain,
        "powers": (office_doc or {}).get("powers") or [],
        "state_powers": (override_doc or {}).get("powers") or [],
        "why_it_matters": pick_why_it_matters(race_doc, locality_doc, office_doc),
        "candidates": candidates,
        "questions": questions,
        "payload": payload,
        "facts": facts,
    }
