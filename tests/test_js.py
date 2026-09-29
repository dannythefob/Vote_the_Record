"""Run the JavaScript scoring tests (tests/js) under Node's built-in test runner.

Node must be installed. Locally the test is skipped with a message if it isn't; in CI
(REQUIRE_NODE=1) a missing Node is a failure, so the scoring tests can't be skipped silently.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def test_javascript_scoring_suite():
    node = shutil.which("node")
    if node is None:
        message = "Node.js is not installed; install Node 20+ to run tests/js (node --test)."
        if os.environ.get("REQUIRE_NODE") == "1":
            pytest.fail(message)
        pytest.skip(message)
    result = subprocess.run(
        [node, "--test", "tests/js/*.test.mjs"],
        cwd=REPO, capture_output=True, text=True, encoding="utf-8",
    )
    assert result.returncode == 0, result.stdout + result.stderr
