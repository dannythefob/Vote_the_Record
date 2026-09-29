"""Real-browser check of the demo build: CSP, survey results, focus, themes, phone width.

Needs Node.js and Chrome, Chromium, or Edge. Skipped locally when either is missing;
set REQUIRE_BROWSER=1 (as CI does) to make a missing browser a failure.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src" / "build"))
from build import build  # noqa: E402

CANDIDATE_BROWSERS = [
    os.environ.get("BROWSER_PATH", ""),
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]


def find_browser():
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "msedge"):
        if shutil.which(name):
            return shutil.which(name)
    return next((p for p in CANDIDATE_BROWSERS if p and Path(p).is_file()), None)


@pytest.fixture(scope="module")
def report(tmp_path_factory):
    node, browser = shutil.which("node"), find_browser()
    if not node or not browser:
        message = f"Browser check needs Node and Chrome/Edge (node={node}, browser={browser})."
        if os.environ.get("REQUIRE_BROWSER") == "1":
            pytest.fail(message)
        pytest.skip(message)
    out = tmp_path_factory.mktemp("demo") / "dist"
    assert build(REPO / "tests" / "fixtures" / "demo", out, demo=True, today="2026-09-29") == 0
    result = subprocess.run([node, str(REPO / "tests" / "browser" / "survey_check.mjs"), str(out), browser],
                            capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_no_csp_violations_console_errors_or_offsite_requests(report):
    assert report["problems"] == {"cspViolations": [], "consoleErrors": [], "offsiteRequests": []}


def test_percentage_matches_methodology_for_avery(report):
    # S-01 alignment 3.0/3.4 at importance 3; S-03 and S-04 aligned at importance 2; S-02 unverified.
    expected = round(100 * (3 * (3.0 / 3.4) + 2 + 2) / 7)
    assert report["survey"]["meters"][0] == expected
    assert "Based on 3 of 4 questions." in report["survey"]["text"]["Avery Example"]


def test_beta_breakdown_and_no_record_states(report):
    survey = report["survey"]
    assert "Not enough record to compare." in survey["text"]["Blake Sample"]
    assert survey["betaBreakdownOpen"] == [False, True, None]
    assert survey["text"]["Casey Placeholder"].endswith("No record on file for this candidate.")
    assert survey["unverifiedBadgesInResults"] >= 2  # unverified record and unverified link


def test_results_alphabetical_and_focus_moves_to_results(report):
    assert report["survey"]["order"] == ["Avery Example", "Blake Sample", "Casey Placeholder"]
    assert report["survey"]["focusedId"] == "results-heading"


def test_dark_mode_reduced_motion_and_phone_width(report):
    assert report["dark"] == "rgb(18, 26, 28)"
    assert report["light"] == "rgb(242, 245, 244)"
    assert report["scrollBehaviorReduced"] == "auto"
    assert report["phoneOverflow"] == 0
