"""Validate every YAML file under data/, offices/, and corrections/.

Checks each file against its JSON Schema (schemas/), then runs cross-file rules
that a schema can't express: path-based IDs, references between facts, mappings
against surveys, and date ordering. See CLAUDE.md for the rules themselves.

Usage: python src/validate/validate.py [repo_root]
Exit code 0 when clean, 1 when any error is found.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

REPO_ROOT = Path(__file__).resolve().parents[2]

# Party names may not appear in survey text (rule 5). Matched as whole words.
PARTY_TERMS = re.compile(
    r"\b(democrat(ic)?s?|republicans?|libertarians?|green party|gop|dnc|rnc)\b",
    re.IGNORECASE,
)

# Which schema applies to a file, by its path relative to the repo root.
FILE_KINDS = [
    (re.compile(r"^offices/[^/]+/powers\.yaml$"), "powers"),
    (re.compile(r"^offices/[^/]+/survey\.yaml$"), "survey"),
    (re.compile(r"^data/states/[a-z]{2}/state\.yaml$"), "state"),
    (re.compile(r"^data/states/[a-z]{2}/office-overrides/[^/]+\.yaml$"), "office_override"),
    (re.compile(r"^data/states/[a-z]{2}/voter-essentials/\d{4}-\d{2}-\d{2}\.yaml$"), "voter_essentials"),
    (re.compile(r"^data/states/[a-z]{2}/localities/[^/]+/locality\.yaml$"), "locality"),
    (re.compile(r"^data/states/[a-z]{2}/localities/[^/]+/actions/\d{4}-\d{2}-\d{2}\.yaml$"), "actions"),
    (re.compile(r"^data/states/[a-z]{2}/(statewide|localities/[^/]+)/elections/\d{4}-\d{2}-\d{2}/[^/]+/race\.yaml$"), "race"),
    (re.compile(r"^data/states/[a-z]{2}/(statewide|localities/[^/]+)/elections/\d{4}-\d{2}-\d{2}/[^/]+/candidates/[^/]+\.yaml$"), "candidate"),
    (re.compile(r"^corrections/log\.yaml$"), "corrections"),
]


class _NoDateLoader(yaml.SafeLoader):
    """SafeLoader that keeps dates as strings so they match the schemas."""


_NoDateLoader.yaml_implicit_resolvers = {
    ch: [(tag, rx) for tag, rx in resolvers if tag != "tag:yaml.org,2002:timestamp"]
    for ch, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)

    def error(self, path: str, message: str) -> None:
        self.errors.append(f"{path}: {message}")


def load_validators(schemas_dir: Path) -> dict[str, Draft202012Validator]:
    schemas = {}
    for schema_file in schemas_dir.glob("*.schema.json"):
        schema = json.loads(schema_file.read_text(encoding="utf-8"))
        schemas[schema["$id"]] = schema
    registry = Registry().with_resources(
        (uri, Resource.from_contents(s)) for uri, s in schemas.items()
    )

    def for_ref(ref: str) -> Draft202012Validator:
        return Draft202012Validator({"$ref": ref}, registry=registry)

    return {
        "candidate": for_ref("urn:vtr:schema:candidate"),
        **{
            kind: for_ref(f"urn:vtr:schema:other#/$defs/{kind}")
            for kind in ("race", "actions", "powers", "office_override", "survey",
                         "state", "locality", "corrections", "voter_essentials")
        },
    }


def classify(rel: str) -> str | None:
    for pattern, kind in FILE_KINDS:
        if pattern.match(rel):
            return kind
    return None


def id_prefix(rel: str) -> str:
    """data/states/tx/a/b.yaml -> tx/a/b"""
    return rel.removeprefix("data/states/").removesuffix(".yaml")


def iter_facts(kind: str, doc: dict):
    """Yield (section, fact) for every fact-like item that carries a path-based ID."""
    if kind == "actions":
        for fact in doc.get("facts") or []:
            yield "facts", fact
    elif kind == "voter_essentials":
        for item in doc.get("items") or []:
            yield "items", item
    elif kind == "candidate":
        for section in ("summary", "records", "funding", "endorsements"):
            for fact in doc.get(section, []):
                yield section, fact
        for section, facts in (doc.get("running_on") or {}).items():
            for fact in facts or []:
                yield f"running_on.{section}", fact


def find_party_keys(node, path: str = ""):
    """Yield paths of any key mentioning 'party' other than ballot_party."""
    if isinstance(node, dict):
        for key, value in node.items():
            here = f"{path}.{key}" if path else str(key)
            if "party" in str(key).lower() and key != "ballot_party":
                yield here
            yield from find_party_keys(value, here)
    elif isinstance(node, list):
        for i, item in enumerate(node):
            yield from find_party_keys(item, f"{path}[{i}]")


def validate(root: Path, schemas_dir: Path | None = None) -> Report:
    """Validate the data repo at root. schemas_dir defaults to root/schemas, else this repo's."""
    report = Report()
    if schemas_dir is None:
        schemas_dir = root / "schemas" if (root / "schemas").is_dir() else REPO_ROOT / "schemas"
    validators = load_validators(schemas_dir)

    docs: dict[str, tuple[str, object]] = {}
    for base in ("data", "offices", "corrections"):
        for file in sorted((root / base).rglob("*.yaml")):
            rel = file.relative_to(root).as_posix()
            kind = classify(rel)
            if kind is None:
                report.error(rel, "unrecognized file location; see CLAUDE.md repository layout")
                continue
            try:
                doc = yaml.load(file.read_text(encoding="utf-8"), Loader=_NoDateLoader)
            except yaml.YAMLError as exc:
                report.error(rel, f"YAML parse error: {exc}")
                continue
            for err in sorted(validators[kind].iter_errors(doc), key=lambda e: list(e.absolute_path)):
                where = "/".join(str(p) for p in err.absolute_path) or "(root)"
                report.error(rel, f"{where}: {err.message}")
            docs[rel] = (kind, doc)

    for rel, (kind, doc) in docs.items():
        for key_path in find_party_keys(doc):
            report.error(rel, f"{key_path}: party may only appear in ballot_party (rule 5)")

    # Offices: powers and surveys.
    powers: dict[str, set[str]] = {}
    surveys: dict[str, dict] = {}
    for rel, (kind, doc) in docs.items():
        if not isinstance(doc, dict):
            continue
        office = rel.split("/")[1] if rel.startswith("offices/") else None
        if kind in ("powers", "survey") and doc.get("office_type") != office:
            report.error(rel, f"office_type must be '{office}' to match its folder")
        if kind == "powers":
            # Merge, don't assign: state overrides (under data/) may already be loaded.
            powers.setdefault(office, set()).update(
                p.get("id") for p in doc.get("powers") or [] if isinstance(p, dict)
            )
        elif kind == "survey":
            surveys[office] = doc
        elif kind == "office_override":
            powers.setdefault(doc.get("office_type"), set()).update(
                p.get("id") for p in doc.get("powers") or [] if isinstance(p, dict)
            )

    # Plain-language summaries may only summarize powers that exist (rule 3).
    for rel, (kind, doc) in docs.items():
        if kind not in ("powers", "office_override") or not isinstance(doc, dict):
            continue
        summary = doc.get("plain_summary") or {}
        office = doc.get("office_type")
        for line in [summary.get("intro") or {}, *(summary.get("points") or [])]:
            for pid in line.get("powers") or []:
                if pid not in powers.get(office, set()):
                    report.error(rel, f"plain_summary: power {pid} does not exist for office '{office}'")

    for office, survey in surveys.items():
        rel = f"offices/{office}/survey.yaml"
        tags = set(survey.get("tags") or [])
        seen = set()
        for scenario in survey.get("scenarios") or []:
            if not isinstance(scenario, dict):
                continue
            sid = scenario.get("id")
            if sid in seen:
                report.error(rel, f"duplicate scenario id {sid}")
            seen.add(sid)
            for pid in scenario.get("powers") or []:
                if pid not in powers.get(office, set()):
                    report.error(rel, f"{sid}: power {pid} is not in offices/{office}/powers.yaml (rule 4)")
            texts = [scenario.get("scenario", "")]
            for option in scenario.get("options") or []:
                texts.append(option.get("text", ""))
                for tag in option.get("tags") or []:
                    if tag not in tags:
                        report.error(rel, f"{sid}/{option.get('id')}: tag '{tag}' is not in the survey's tag list")
                if PARTY_TERMS.search(" ".join(option.get("tags") or [])):
                    report.error(rel, f"{sid}/{option.get('id')}: tags may not name a party (rule 5)")
            for text in texts:
                if PARTY_TERMS.search(text or ""):
                    report.error(rel, f"{sid}: scenario text mentions a party (rule 5)")

    # Facts: path-based IDs, uniqueness, date order.
    all_ids: dict[str, str] = {}
    for rel, (kind, doc) in docs.items():
        if not isinstance(doc, dict):
            continue
        prefix = id_prefix(rel)
        for section, fact in iter_facts(kind, doc):
            if not isinstance(fact, dict):
                continue
            fid = fact.get("id", "")
            if not str(fid).startswith(prefix + "#"):
                report.error(rel, f"{section}: id '{fid}' must start with '{prefix}#' (path-based IDs)")
            if fid in all_ids:
                report.error(rel, f"{section}: duplicate id '{fid}' (also in {all_ids[fid]})")
            all_ids[fid] = rel
            if fact.get("verification") == "verified":
                retrieved, verified_on = fact.get("retrieved"), fact.get("verified_on")
                if isinstance(retrieved, str) and isinstance(verified_on, str) and verified_on < retrieved:
                    report.error(rel, f"{fid}: verified_on {verified_on} is earlier than retrieved {retrieved}")

    # References between facts, mappings, and surveys.
    for rel, (kind, doc) in docs.items():
        if not isinstance(doc, dict):
            continue
        for section, fact in iter_facts(kind, doc):
            if not isinstance(fact, dict):
                continue
            for ref in fact.get("contradicted_by") or []:
                if ref not in all_ids:
                    report.error(rel, f"{fact.get('id')}: contradicted_by '{ref}' does not exist")
        if kind != "candidate":
            continue

        race_rel = rel.rsplit("/candidates/", 1)[0] + "/race.yaml"
        race_kind, race = docs.get(race_rel, (None, None))
        office = race.get("office_type") if isinstance(race, dict) else None
        if race_kind != "race":
            report.error(rel, f"missing {race_rel}")
        record_ids = {r.get("id") for r in doc.get("records") or [] if isinstance(r, dict)}

        photo = doc.get("photo")
        if isinstance(photo, dict) and photo.get("file"):
            if not (root / rel).parent.joinpath(photo["file"]).is_file():
                report.error(rel, f"photo: file '{photo['file']}' not found next to the candidate file")

        for i, mapping in enumerate(doc.get("mappings") or []):
            if not isinstance(mapping, dict):
                continue
            where = f"mappings[{i}]"
            if mapping.get("record") not in record_ids:
                report.error(rel, f"{where}: record '{mapping.get('record')}' is not in this candidate's records")
            question = str(mapping.get("question", ""))
            q_office, _, q_id = question.partition("/")
            if office and q_office != office:
                report.error(rel, f"{where}: question '{question}' is not for this race's office '{office}'")
                continue
            scenario = next(
                (s for s in (surveys.get(q_office) or {}).get("scenarios") or []
                 if isinstance(s, dict) and s.get("id") == q_id),
                None,
            )
            if scenario is None:
                report.error(rel, f"{where}: question '{question}' does not exist")
                continue
            option_ids = {o.get("id") for o in scenario.get("options") or []}
            for option in mapping.get("options") or []:
                if option not in option_ids:
                    report.error(rel, f"{where}: option '{option}' is not in {question}")

        for i, entry in enumerate(doc.get("promise_tracker") or []):
            if not isinstance(entry, dict):
                continue
            for ref in [entry.get("promise"), *(entry.get("evidence") or [])]:
                if ref not in all_ids:
                    report.error(rel, f"promise_tracker[{i}]: '{ref}' does not exist")

    return report


def main(argv: list[str]) -> int:
    root = Path(argv[1]).resolve() if len(argv) > 1 else REPO_ROOT
    report = validate(root)
    for line in report.errors:
        print(f"ERROR {line}")
    print(f"{len(report.errors)} error(s)")
    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
