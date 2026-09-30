"""The owner's report reader: key listing and plain-text formatting (no network)."""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src" / "review"))
from reports import format_report, list_keys  # noqa: E402


def test_keys_come_back_oldest_first():
    listing = json.dumps([{"name": "report:2026-10-02T09:00:00.000Z:bbbb"},
                          {"name": "report:2026-10-01T09:00:00.000Z:aaaa"}])
    calls = []

    def fake(*args):
        calls.append(args)
        return listing

    assert list_keys(fake) == ["report:2026-10-01T09:00:00.000Z:aaaa", "report:2026-10-02T09:00:00.000Z:bbbb"]
    assert calls == [("list", "--prefix", "report:")]


def test_format_shows_every_field_and_marks_blanks():
    raw = json.dumps({"received": "2026-10-01T09:00:00.000Z", "item": "tx/x#F-001",
                      "problem": "The date is wrong.", "source": "", "contact": ""})
    text = format_report("report:k", raw)
    assert text.splitlines() == ["== report:k", "Received: 2026-10-01T09:00:00.000Z", "Item: tx/x#F-001",
                                 "Problem: The date is wrong.", "Source: (none)", "Contact: (none)"]
