"""The owner's review tool must change only the three verification lines of the confirmed item."""

import difflib
import json
import shutil
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src" / "review"))
import review  # noqa: E402

CAND = "data/states/tx/localities/harris-county/elections/2026-11-03/county-judge/candidates"
PLUMMER = f"{CAND}/letitia-plummer.yaml"
B02 = "tx/localities/harris-county/elections/2026-11-03/county-judge/candidates/letitia-plummer#B-02"
R01 = "tx/localities/harris-county/elections/2026-11-03/county-judge/candidates/letitia-plummer#R-01"


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    for part in ("data", "offices", "corrections", "schemas"):
        shutil.copytree(REPO / part, root / part)
    # Start from a known state: the owner may have verified these in the real data.
    review.set_verification(root / PLUMMER, "fact", B02, False)
    review.set_verification(root / PLUMMER, "fact", R01, False)
    review.set_verification(root / PLUMMER, "mapping", f"{R01}|county-judge/S-06", False)
    return root


def changed_lines(before: str, after: str) -> list[str]:
    return [l for l in difflib.unified_diff(before.splitlines(), after.splitlines(), lineterm="", n=0)
            if l[:1] in "+-" and not l.startswith(("+++", "---"))]


def test_lists_every_fact_and_mapping(repo):
    items = review.load_items(repo)
    keys = {i["key"] for i in items}
    assert B02 in keys
    assert f"{R01}|county-judge/S-06" in keys
    assert all(i["verification"] in ("verified", "unverified") for i in items)


def test_verify_changes_only_three_lines_and_undo_restores(repo):
    path = repo / PLUMMER
    original = path.read_text(encoding="utf-8")
    assert review.apply(repo, "fact", PLUMMER, B02, True, "Test Reviewer") is None
    after = path.read_text(encoding="utf-8")
    diff = changed_lines(original, after)
    assert len(diff) == 6  # three removed, three added
    assert '+    verification: verified' in diff
    assert '+    reviewer: "Test Reviewer"' in diff
    item = next(i for i in review.load_items(repo) if i["key"] == B02)
    assert item["verification"] == "verified" and item["reviewer"] == "Test Reviewer"
    assert review.apply(repo, "fact", PLUMMER, B02, False, "Test Reviewer") is None
    assert path.read_text(encoding="utf-8") == original


def test_verify_mapping(repo):
    key = f"{R01}|county-judge/S-06"
    assert review.apply(repo, "mapping", PLUMMER, key, True, "Test Reviewer") is None
    item = next(i for i in review.load_items(repo) if i["key"] == key)
    assert item["verification"] == "verified"
    other = next(i for i in review.load_items(repo) if i["key"] == R01)
    assert other["verification"] == "unverified"  # the record itself is untouched


def test_blocked_when_no_archive(repo):
    path = repo / PLUMMER
    text = path.read_text(encoding="utf-8")
    start = text.index(B02)
    line = text.index("archive_url:", start)
    end = text.index("\n", line)
    path.write_text(text[:line] + "archive_url: null" + text[end:], encoding="utf-8")
    error = review.apply(repo, "fact", PLUMMER, B02, True, "Test Reviewer")
    assert error and "archived copy" in error
    assert next(i for i in review.load_items(repo) if i["key"] == B02)["verification"] == "unverified"


def test_refuses_items_without_their_own_verification_lines(tmp_path):
    demo = tmp_path / "demo"
    shutil.copytree(REPO / "tests" / "fixtures" / "demo", demo)
    file = ("data/states/tx/localities/demo-county/elections/2026-11-03/"
            "commissioner-precinct-9/candidates/02-avery-example.yaml")
    key = "tx/localities/demo-county/elections/2026-11-03/commissioner-precinct-9/candidates/02-avery-example#R-06"
    with pytest.raises(ValueError, match="its own"):
        review.set_verification(demo / file, "fact", key, True, "Test Reviewer")


def test_refuses_paths_outside_data(repo):
    assert "Only files under data/" in review.apply(repo, "fact", "../CLAUDE.md", B02, True, "x")


def test_http_requires_token_and_localhost(repo, tmp_path):
    token = "secret-token"
    server = ThreadingHTTPServer(("127.0.0.1", 0), review.make_handler(repo, token, tmp_path / ".reviewer"))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    body = json.dumps({"type": "fact", "file": PLUMMER, "key": B02, "verified": True, "reviewer": "T"}).encode()

    def post(headers):
        req = urllib.request.Request(base + "/api/set", data=body, method="POST",
                                     headers={"Content-Type": "application/json", **headers})
        try:
            return urllib.request.urlopen(req).status
        except urllib.error.HTTPError as exc:
            return exc.code

    assert post({}) == 403
    assert post({"X-Review-Token": "wrong"}) == 403
    assert post({"X-Review-Token": token}) == 200
    assert "verification: verified" in (repo / PLUMMER).read_text(encoding="utf-8")
    page = urllib.request.urlopen(base + "/").read().decode()
    assert token in page
    server.shutdown()


def test_finds_every_item_in_the_real_data(repo):
    # Regression: every listed item must be locatable for writing, however its ID is wrapped.
    for item in review.load_items(repo):
        lines = (repo / item["file"]).read_text(encoding="utf-8").split("\n")
        review._block_span(lines, item["type"], item["key"])


def test_finds_fact_whose_id_is_wrapped_onto_the_next_line(repo):
    path = repo / PLUMMER
    text = path.read_text(encoding="utf-8")
    text = text.replace(f"  - id: {B02}\n", f"  - id: >-\n      {B02}\n")
    path.write_text(text, encoding="utf-8")
    assert review.apply(repo, "fact", PLUMMER, B02, True, "Test Reviewer") is None
    assert next(i for i in review.load_items(repo) if i["key"] == B02)["verification"] == "verified"


# --- Verify all in a group ---------------------------------------------------

GOV = "data/states/tx/statewide/elections/2026-11-03/governor/race.yaml"
GOV_S01 = "tx/statewide/elections/2026-11-03/governor/race#S-01"
GOV_S02 = "tx/statewide/elections/2026-11-03/governor/race#S-02"  # write-in list: no archive yet
AG = "data/states/tx/statewide/elections/2026-11-03/attorney-general/race.yaml"
AG_S01 = "tx/statewide/elections/2026-11-03/attorney-general/race#S-01"


def test_race_ballot_zip_and_precinct_sources_are_listed(repo):
    files = {i["file"].rsplit("/", 1)[-1] for i in review.load_items(repo)}
    assert {"race.yaml", "ballot.yaml", "zips.yaml", "precincts.yaml"} <= files
    item = next(i for i in review.load_items(repo) if i["key"] == GOV_S01)
    assert item["who"] == "Governor" and item["section"] == "sources"


def test_verify_many_changes_only_ready_facts_and_their_three_lines(repo):
    before = {f: (repo / f).read_text(encoding="utf-8") for f in (GOV, AG)}
    result = review.apply_many(repo, [{"file": GOV, "key": GOV_S01}, {"file": GOV, "key": GOV_S02},
                                      {"file": AG, "key": AG_S01}], "Test Reviewer")
    assert result["ok"] and result["verified"] == 2
    assert len(result["skipped"]) == 1 and "S-02" in result["skipped"][0] and "archived copy" in result["skipped"][0]
    for f in (GOV, AG):
        diff = changed_lines(before[f], (repo / f).read_text(encoding="utf-8"))
        assert len(diff) == 6 and '+  reviewer: "Test Reviewer"' in diff
    states = {i["key"]: i["verification"] for i in review.load_items(repo)}
    assert states[GOV_S01] == states[AG_S01] == "verified" and states[GOV_S02] == "unverified"


def test_verify_many_is_all_or_nothing(repo, monkeypatch):
    before = {f: (repo / f).read_text(encoding="utf-8") for f in (GOV, AG)}

    class Fail:
        errors = [f"{AG}: pretend the checker found a problem"]
    monkeypatch.setattr(review, "validate", lambda root: Fail)
    result = review.apply_many(repo, [{"file": GOV, "key": GOV_S01}, {"file": AG, "key": AG_S01}], "Test Reviewer")
    assert not result["ok"] and "nothing was changed" in result["error"]
    for f in (GOV, AG):
        assert (repo / f).read_text(encoding="utf-8") == before[f]


def test_verify_many_needs_a_reviewer_and_skips_unknown_keys(repo):
    assert not review.apply_many(repo, [{"file": GOV, "key": GOV_S01}], "")["ok"]
    result = review.apply_many(repo, [{"file": GOV, "key": "tx/nope#X-1"}], "Test Reviewer")
    assert result["ok"] and result["verified"] == 0 and "not found" in result["skipped"][0]


def test_verify_many_endpoint_requires_token(repo, tmp_path):
    server = ThreadingHTTPServer(("127.0.0.1", 0), review.make_handler(repo, "secret", tmp_path / ".reviewer"))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}/api/verify-many"
    body = json.dumps({"reviewer": "Test Reviewer", "changes": [{"file": GOV, "key": GOV_S01}]}).encode()
    try:
        bad = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        with pytest.raises(urllib.error.HTTPError):
            urllib.request.urlopen(bad)
        good = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", "X-Review-Token": "secret"})
        result = json.loads(urllib.request.urlopen(good).read())
        assert result["ok"] and result["verified"] == 1
    finally:
        server.shutdown()
