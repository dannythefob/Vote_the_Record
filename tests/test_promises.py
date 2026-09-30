"""Promise tracker counts and kept rate (docs/METHODOLOGY.md, Promise tracker)."""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src" / "build"))
from model import promise_score  # noqa: E402

OK = {"verification": "verified", "claim_status": "documented"}
UNVERIFIED = {"verification": "unverified", "claim_status": "documented"}
DISPUTED = {"verification": "verified", "claim_status": "disputed"}


def promise(status, fact=OK, evidence=(OK,)):
    return {"status": status, "promise_fact": fact,
            "evidence_facts": [] if status == "pending" else list(evidence)}


def test_counts_and_rate_once_three_are_decided():
    card = promise_score([promise("kept"), promise("kept"), promise("broken"),
                          promise("opposite"), promise("pending")])
    assert card["counts"] == {"kept": 2, "broken": 1, "opposite": 1, "pending": 1}
    assert card["made"] == 5 and card["decided"] == 4
    assert card["rate"] == 50  # still-open promises are not in the rate


def test_no_rate_below_three_decided():
    card = promise_score([promise("kept"), promise("opposite"), promise("pending"), promise("pending")])
    assert card["decided"] == 2 and card["rate"] is None


def test_exactly_three_decided_shows_rate():
    assert promise_score([promise("kept"), promise("kept"), promise("broken")])["rate"] == 67


def test_unchecked_promises_and_evidence_are_not_counted():
    card = promise_score([
        promise("kept", fact=UNVERIFIED),
        promise("kept", evidence=(OK, UNVERIFIED)),
        promise("broken", evidence=(DISPUTED,)),
        promise("kept", evidence=(None,)),  # missing evidence fact
        promise("pending", fact=None),
        promise("kept"),
    ])
    assert card["unchecked"] == 5
    assert card["counts"]["kept"] == 1 and card["made"] == 1 and card["rate"] is None
