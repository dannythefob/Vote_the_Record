"""wrangler.jsonc must agree with what the build produces, so deploys fail in CI, not on Cloudflare."""

import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src" / "build"))
from build import MARKER, SITE, build  # noqa: E402


def load_jsonc(path: Path) -> dict:
    text = re.sub(r"^\s*//.*$", "", path.read_text(encoding="utf-8"), flags=re.M)
    return json.loads(text)


@pytest.fixture(scope="module")
def config():
    return load_jsonc(REPO / "wrangler.jsonc")


@pytest.fixture(scope="module")
def dist(tmp_path_factory):
    out = tmp_path_factory.mktemp("w") / "dist"
    assert build(REPO, out, today="2026-09-29") == 0
    return out


def test_assets_directory_is_the_build_output(config):
    assert (REPO / config["assets"]["directory"]).resolve() == (SITE / "dist").resolve()


def test_worker_name_and_compatibility_date(config):
    assert config["name"] == "vote-the-record"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", config["compatibility_date"])


def test_worker_script_only_runs_for_the_report_api(config):
    # Pages are static; the Worker runs first only for /api/*, so page views never reach code.
    assert config["main"] == "src/worker/index.js"
    assert (REPO / config["main"]).is_file()
    assert config["assets"]["binding"] == "ASSETS"
    assert config["assets"]["run_worker_first"] == ["/api/*"]


def test_reports_are_stored_in_the_REPORTS_kv_namespace(config):
    [kv] = config["kv_namespaces"]
    assert kv["binding"] == "REPORTS"
    assert kv["id"]


def test_missing_pages_use_the_site_404(config, dist):
    assert config["assets"]["not_found_handling"] == "404-page"
    assert (dist / "404.html").is_file()


def test_build_marker_is_not_uploaded(dist):
    assert (dist / MARKER).is_file()
    ignored = (dist / ".assetsignore").read_text(encoding="utf-8").split()
    assert MARKER in ignored


def test_headers_file_sits_at_the_assets_root(dist):
    assert (dist / "_headers").is_file()
