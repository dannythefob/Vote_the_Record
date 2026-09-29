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


def test_assets_only_worker_has_no_script(config):
    # The site is static: no server code runs, so nothing can collect visitor data.
    assert "main" not in config


def test_missing_pages_use_the_site_404(config, dist):
    assert config["assets"]["not_found_handling"] == "404-page"
    assert (dist / "404.html").is_file()


def test_build_marker_is_not_uploaded(dist):
    assert (dist / MARKER).is_file()
    ignored = (dist / ".assetsignore").read_text(encoding="utf-8").split()
    assert MARKER in ignored


def test_headers_file_sits_at_the_assets_root(dist):
    assert (dist / "_headers").is_file()
