"""Each test builds a tiny repo in a temp dir and checks one validator rule."""

import copy
import shutil
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src" / "validate"))
from validate import validate  # noqa: E402

RACE_DIR = "data/states/tx/localities/test-county/elections/2026-11-03/test-race"
CAND_REL = f"{RACE_DIR}/candidates/pat-doe.yaml"
PREFIX = "tx/localities/test-county/elections/2026-11-03/test-race/candidates/pat-doe"

FACT = {
    "id": f"{PREFIX}#F-001",
    "record_type": "vote",
    "same_event": "tx/localities/test-county/actions/2025-01-01#item-1",
    "statement": "Voted yes on Item 1.",
    "label": "official_record",
    "claim_status": "documented",
    "source_url": "https://example.gov/minutes.pdf",
    "source_title": "Minutes",
    "source_kind": "document",
    "sha256": None,
    "archive_url": None,
    "event_date": "2025-01-01",
    "retrieved": None,
    "verification": "unverified",
    "verified_on": None,
    "reviewer": None,
}

VERIFIED = {
    "sha256": "a" * 64,
    "archive_url": "https://web.archive.org/web/2025/https://example.gov/minutes.pdf",
    "retrieved": "2025-02-01",
    "verification": "verified",
    "verified_on": "2025-02-02",
    "reviewer": "owner",
}

SURVEY = {
    "office_type": "test-office",
    "tags": ["use-reserves", "cut-spending"],
    "scenarios": [{
        "id": "S-01",
        "powers": ["P-BUDGET"],
        "scenario": "Revenue falls short mid-year.",
        "options": [
            {"id": "A", "text": "Cut spending.", "tags": ["cut-spending"]},
            {"id": "B", "text": "Use reserves.", "tags": ["use-reserves"]},
        ],
    }],
}


def candidate(**overrides):
    doc = {
        "id": "pat-doe", "name": "Pat Doe", "incumbent": True, "ballot_party": None,
        "records": [copy.deepcopy(FACT)], "funding": [], "endorsements": [],
        "running_on": {"policy_proposals": [], "attack_messaging": [], "contested_claims": []},
        "mappings": [], "promise_tracker": [],
    }
    doc.update(overrides)
    return doc


def build(tmp_path, cand=None, survey=None):
    shutil.copytree(REPO / "schemas", tmp_path / "schemas")
    files = {
        "offices/test-office/powers.yaml": {"office_type": "test-office", "powers": [
            {"id": "P-BUDGET", "description": "Adopts the budget.", "source_url": "https://example.gov/law"}]},
        "offices/test-office/survey.yaml": survey or SURVEY,
        f"{RACE_DIR}/race.yaml": {"name": "Test Race", "office_type": "test-office", "election_date": "2026-11-03"},
        CAND_REL: cand or candidate(),
    }
    for rel, doc in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return validate(tmp_path).errors


def with_fact(**changes):
    fact = {**FACT, **changes}
    return candidate(records=[fact])


def test_valid_unverified_passes(tmp_path):
    assert build(tmp_path) == []


def test_valid_verified_passes(tmp_path):
    assert build(tmp_path, with_fact(**VERIFIED)) == []


def test_verified_without_archive_url_fails(tmp_path):
    errors = build(tmp_path, with_fact(**{**VERIFIED, "archive_url": None}))
    assert any("archive_url" in e for e in errors)


def test_verified_on_before_retrieved_fails(tmp_path):
    errors = build(tmp_path, with_fact(**{**VERIFIED, "verified_on": "2025-01-15"}))
    assert any("earlier than retrieved" in e for e in errors)


def test_verified_document_without_sha256_fails(tmp_path):
    errors = build(tmp_path, with_fact(**{**VERIFIED, "sha256": None}))
    assert any("sha256" in e for e in errors)


def test_page_source_with_sha256_fails(tmp_path):
    errors = build(tmp_path, with_fact(source_kind="page", sha256="b" * 64))
    assert any("sha256" in e for e in errors)


def test_verified_page_without_sha256_passes(tmp_path):
    assert build(tmp_path, with_fact(**{**VERIFIED, "source_kind": "page", "sha256": None})) == []


def test_unverified_with_reviewer_fails(tmp_path):
    errors = build(tmp_path, with_fact(reviewer="someone"))
    assert any("reviewer" in e for e in errors)


def test_missing_source_url_fails(tmp_path):
    fact = {k: v for k, v in FACT.items() if k != "source_url"}
    errors = build(tmp_path, candidate(records=[fact]))
    assert any("source_url" in e for e in errors)


def test_id_not_matching_path_fails(tmp_path):
    errors = build(tmp_path, with_fact(id="tx/elsewhere/pat-doe#F-001"))
    assert any("path-based" in e for e in errors)


def test_contradicted_requires_evidence(tmp_path):
    errors = build(tmp_path, with_fact(claim_status="contradicted"))
    assert any("contradicted_by" in e for e in errors)


def test_contradicted_by_must_exist(tmp_path):
    errors = build(tmp_path, with_fact(claim_status="contradicted", contradicted_by=[f"{PREFIX}#F-999"]))
    assert any("does not exist" in e for e in errors)


def mapping(**changes):
    return {"record": FACT["id"], "question": "test-office/S-01", "options": ["B"],
            "rationale": "Voted to draw on reserves.", "verification": "unverified",
            "verified_on": None, "reviewer": None, **changes}


def test_mapping_with_multiple_options_passes(tmp_path):
    assert build(tmp_path, candidate(mappings=[mapping(options=["A", "B"])])) == []


def test_mapping_unknown_option_fails(tmp_path):
    errors = build(tmp_path, candidate(mappings=[mapping(options=["Z"])]))
    assert any("option 'Z'" in e for e in errors)


def test_mapping_without_rationale_fails(tmp_path):
    errors = build(tmp_path, candidate(mappings=[mapping(rationale="")]))
    assert any("rationale" in e or "short" in e for e in errors)


def test_promise_kept_requires_evidence(tmp_path):
    errors = build(tmp_path, candidate(promise_tracker=[{"promise": FACT["id"], "status": "kept", "evidence": []}]))
    assert any("promise_tracker" in e for e in errors)


def test_party_key_outside_ballot_party_fails(tmp_path):
    cand = candidate()
    cand["records"][0]["party"] = "X"
    errors = build(tmp_path, cand)
    assert any("ballot_party" in e for e in errors)


def test_party_in_scenario_text_fails(tmp_path):
    survey = copy.deepcopy(SURVEY)
    survey["scenarios"][0]["scenario"] = "Republicans propose cuts."
    errors = build(tmp_path, survey=survey)
    assert any("mentions a party" in e for e in errors)


def test_scenario_power_must_exist(tmp_path):
    survey = copy.deepcopy(SURVEY)
    survey["scenarios"][0]["powers"] = ["P-NOPE"]
    errors = build(tmp_path, survey=survey)
    assert any("P-NOPE" in e for e in errors)


def test_option_tag_must_be_listed(tmp_path):
    survey = copy.deepcopy(SURVEY)
    survey["scenarios"][0]["options"][0]["tags"] = ["unlisted"]
    errors = build(tmp_path, survey=survey)
    assert any("unlisted" in e for e in errors)


def test_candidate_summary_facts_are_validated(tmp_path):
    good = {**FACT, "id": f"{PREFIX}#B-001"}
    good.pop("record_type")
    assert build(tmp_path, candidate(summary=[good])) == []


def test_candidate_summary_fact_without_source_fails(tmp_path):
    bad = {k: v for k, v in FACT.items() if k not in ("record_type", "source_url")}
    bad["id"] = f"{PREFIX}#B-001"
    errors = build(tmp_path, candidate(summary=[bad]))
    assert any("source_url" in e for e in errors)


def write(tmp_path, rel, doc):
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")


def test_why_it_matters_requires_a_source(tmp_path):
    build(tmp_path)
    write(tmp_path, f"{RACE_DIR}/race.yaml", {
        "name": "Test Race", "office_type": "test-office", "election_date": "2026-11-03",
        "why_it_matters": [{"text": "It sets the budget."}]})
    errors = validate(tmp_path).errors
    assert any("source_url" in e for e in errors)


def test_why_it_matters_allowed_on_office_locality_and_race(tmp_path):
    reason = [{"text": "It sets the budget.", "source_url": "https://example.gov/law"}]
    build(tmp_path)
    write(tmp_path, "offices/test-office/powers.yaml", {"office_type": "test-office", "why_it_matters": reason,
          "powers": [{"id": "P-BUDGET", "description": "Adopts the budget.", "source_url": "https://example.gov/law"}]})
    write(tmp_path, "data/states/tx/localities/test-county/locality.yaml", {
        "locality": "test-county", "type": "county", "state": "TX", "sources": [], "why_it_matters": reason})
    write(tmp_path, f"{RACE_DIR}/race.yaml", {"name": "Test Race", "office_type": "test-office",
          "election_date": "2026-11-03", "why_it_matters": reason})
    assert validate(tmp_path).errors == []


def test_voter_essentials_need_path_based_ids(tmp_path):
    build(tmp_path)
    write(tmp_path, "data/states/tx/voter-essentials/2026-11-03.yaml", {
        "state": "TX", "election_date": "2026-11-03", "items": [{
            "id": "tx/elsewhere#reg", "name": "Register", "date": "2026-10-05",
            "source_url": "https://example.gov", "source_title": "Dates", "source_kind": "page",
            "sha256": None, "archive_url": None, "retrieved": "2026-09-28",
            "verification": "unverified", "verified_on": None, "reviewer": None}]})
    errors = validate(tmp_path).errors
    assert any("path-based" in e for e in errors)
