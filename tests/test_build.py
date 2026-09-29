"""Stage 1 site build tests: generator, validator gate, pages, headers, CSP hygiene."""

import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src" / "build"))
from build import build  # noqa: E402

TODAY = "2026-09-28"
ESS_REL = "data/states/tx/voter-essentials/2026-11-03.yaml"
ESS_PREFIX = "tx/voter-essentials/2026-11-03"


def essential(local_id, name, **fields):
    item = {
        "id": f"{ESS_PREFIX}#{local_id}", "name": name,
        "source_url": "https://example.gov/dates", "source_title": "Important dates",
        "source_kind": "page", "sha256": None, "archive_url": None, "retrieved": "2026-09-28",
        "verification": "unverified", "verified_on": None, "reviewer": None,
    }
    item.update(fields)
    return item


ESSENTIALS = {
    "state": "TX", "election_date": "2026-11-03",
    "items": [
        essential("election-day", "Election Day", date="2026-11-03"),
        essential("registration-deadline", "Last day to register to vote", date="2026-10-05"),
        essential("early-voting", "Early voting in person", start="2026-10-19", end="2026-10-30"),
    ],
}


def make_repo(tmp_path, files):
    root = tmp_path / "repo"
    for rel, doc in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    for base in ("data", "offices", "corrections"):
        (root / base).mkdir(parents=True, exist_ok=True)
    return root


def make_config(tmp_path, **overrides):
    config = yaml.safe_load((REPO / "site" / "site.yaml").read_text(encoding="utf-8"))
    config.update(overrides)
    path = tmp_path / "site.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    return path


def read(out, page):
    return (out / page).read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def real_site(tmp_path_factory):
    out = tmp_path_factory.mktemp("real") / "dist"
    assert build(REPO, out, today=TODAY) == 0
    return out


def test_real_repo_builds_all_stage1_pages(real_site):
    for page in ("index.html", "about/index.html", "methodology/index.html",
                 "corrections/index.html", "404.html"):
        assert (real_site / page).is_file(), page


def test_home_has_beta_banner_official_links_and_race_list(real_site):
    home = read(real_site, "index.html")
    assert "<strong>Beta.</strong>" in home
    assert 'href="https://www.votetexas.gov/"' in home
    assert 'href="/races/tx/harris-county/2026-11-03/county-judge/"' in home


def test_empty_repo_shows_no_races_state(tmp_path):
    out = tmp_path / "dist"
    assert build(make_repo(tmp_path, {}), out, today=TODAY) == 0
    assert "No races published yet" in read(out, "index.html")


def test_beta_banner_is_sitewide(real_site):
    for page in ("about/index.html", "methodology/index.html", "corrections/index.html"):
        assert "<strong>Beta.</strong>" in read(real_site, page), page


def test_headers_file_has_csp_and_privacy_headers(real_site):
    headers = real_site / "_headers"
    assert headers.is_file()
    text = headers.read_text(encoding="utf-8")
    assert ("Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self'; "
            "font-src 'self'; img-src 'self'; connect-src 'none'; object-src 'none'; "
            "frame-ancestors 'none'; base-uri 'none'; form-action 'none'") in text
    assert "Referrer-Policy: no-referrer" in text
    assert "Permissions-Policy:" in text


def test_methodology_renders_markdown_tables_without_placeholder(real_site):
    page = read(real_site, "methodology/index.html")
    assert page.count("<table>") >= 3
    assert "CORRECTIONS_FORM_URL" not in page
    assert page.count("<h1") == 1


def test_build_fails_and_writes_nothing_when_validator_fails(tmp_path):
    bad = dict(ESSENTIALS, items=[essential("x", "Bad", date="2026-10-05", verification="verified",
                                            verified_on="2026-09-28", reviewer="owner")])
    root = make_repo(tmp_path, {ESS_REL: bad})  # verified without archive_url
    out = tmp_path / "dist"
    assert build(root, out, today=TODAY) == 1
    assert not out.exists()


def test_cli_exits_nonzero_on_validation_error(tmp_path):
    bad = dict(ESSENTIALS, items=[essential("x", "Bad", date="2026-10-05", start="2026-10-01")])
    root = make_repo(tmp_path, {ESS_REL: bad})
    result = subprocess.run(
        [sys.executable, str(REPO / "src" / "build" / "build.py"), "--root", str(root),
         "--out", str(tmp_path / "dist"), "--today", TODAY],
        capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert "Nothing was written" in result.stderr
    assert not (tmp_path / "dist").exists()


def test_bad_corrections_form_config_fails(tmp_path):
    root = make_repo(tmp_path, {})
    config = make_config(tmp_path, corrections_form_url="http://example.org/form")
    assert build(root, tmp_path / "dist", config_path=config, today=TODAY) == 1


def test_voter_essentials_render_sorted_with_badges_and_sources(tmp_path):
    root = make_repo(tmp_path, {ESS_REL: ESSENTIALS})
    out = tmp_path / "dist"
    assert build(root, out, today=TODAY) == 0
    home = read(out, "index.html")
    reg = home.index("Monday, October 5, 2026")
    early = home.index("Monday, October 19, 2026 to Friday, October 30, 2026")
    eday = home.index("Last day to register") and home.index("Election Day:")
    assert reg < early < eday
    assert home.count('class="badge badge-unverified"') >= 3 + 1  # items + banner
    assert home.count('href="https://example.gov/dates"') == 3
    assert "Corrections form coming soon" in home


def test_past_elections_are_not_listed(tmp_path):
    root = make_repo(tmp_path, {ESS_REL: ESSENTIALS})
    out = tmp_path / "dist"
    assert build(root, out, today="2026-11-04") == 0
    assert "Last day to register" not in read(out, "index.html")


def test_unconfigured_form_renders_plain_text_not_links(tmp_path):
    root = make_repo(tmp_path, {ESS_REL: ESSENTIALS})
    out = tmp_path / "dist"
    assert build(root, out, today=TODAY) == 0
    for page in ("index.html", "corrections/index.html", "methodology/index.html", "about/index.html"):
        html = read(out, page)
        assert "Corrections form coming soon" in html, page
        assert "Report a problem</a>" not in html, page


def test_configured_form_links_carry_encoded_item_id(tmp_path):
    root = make_repo(tmp_path, {ESS_REL: ESSENTIALS})
    config = make_config(tmp_path, corrections_form_url="https://forms.example.org/vtr?item={id}")
    out = tmp_path / "dist"
    assert build(root, out, config_path=config, today=TODAY) == 0
    home = read(out, "index.html")
    assert ('href="https://forms.example.org/vtr?item=tx%2Fvoter-essentials%2F2026-11-03'
            '%23registration-deadline"') in home
    assert "Corrections form coming soon" not in home
    assert 'href="https://forms.example.org/vtr?item="' in read(out, "corrections/index.html")


def test_corrections_log_is_newest_first(tmp_path):
    entry = {"target": "tx/x#F-001", "change": "c", "reason": "r",
             "source_url": "https://example.gov/e", "reviewer": "owner"}
    log = [dict(entry, date="2026-01-02", change="older"), dict(entry, date="2026-03-04", change="newer")]
    root = make_repo(tmp_path, {"corrections/log.yaml": log})
    out = tmp_path / "dist"
    assert build(root, out, today=TODAY) == 0
    page = read(out, "corrections/index.html")
    assert page.index("newer") < page.index("older")


def test_refuses_to_replace_a_folder_it_did_not_create(tmp_path):
    out = tmp_path / "precious"
    out.mkdir()
    (out / "keep.txt").write_text("mine")
    with pytest.raises(SystemExit):
        build(make_repo(tmp_path, {}), out, today=TODAY)
    assert (out / "keep.txt").exists()


def test_rebuild_replaces_previous_output(tmp_path):
    out = tmp_path / "dist"
    root = make_repo(tmp_path, {})
    assert build(root, out, today=TODAY) == 0
    (out / "stale.html").write_text("old")
    assert build(root, out, today=TODAY) == 0
    assert not (out / "stale.html").exists()


# CSP hygiene: pages must work under script-src/style-src 'self' with no inline code.
INLINE_PATTERNS = {
    "style attribute": re.compile(r"<[^>]+\sstyle\s*=", re.I),
    "style element": re.compile(r"<style[\s>]", re.I),
    "event handler": re.compile(r"<[^>]+\son[a-z]+\s*=", re.I),
    "inline script": re.compile(r"<script(?![^>]*\bsrc=)(?![^>]*type=\"application/json\")[^>]*>", re.I),
}


def test_pages_have_no_inline_code_or_third_party_assets(real_site):
    for page in real_site.rglob("*.html"):
        html = page.read_text(encoding="utf-8")
        for name, pattern in INLINE_PATTERNS.items():
            assert not pattern.search(html), f"{name} in {page}"
        for tag, attr in (("script", "src"), ("link", "href")):
            for url in re.findall(rf'<{tag}\b[^>]*\b{attr}="([^"]+)"', html):
                assert url.startswith("/") and not url.startswith("//"), f"third-party {tag} {url} in {page}"
    css = (real_site / "static" / "css" / "site.css").read_text(encoding="utf-8")
    for url in re.findall(r"url\(\"?([^\")]+)", css):
        assert url.startswith("/static/"), url
    assert "@import" not in css


# ---- Stage 2: race pages from the fictional demo fixture ----
DEMO = REPO / "tests" / "fixtures" / "demo"
RACE_PAGE = "races/tx/demo-county/2026-11-03/commissioner-precinct-9/index.html"


@pytest.fixture(scope="module")
def demo_site(tmp_path_factory):
    out = tmp_path_factory.mktemp("demo") / "dist"
    assert build(DEMO, out, demo=True, today="2026-09-29") == 0
    return out


def test_demo_banner_on_every_page(demo_site):
    for page in demo_site.rglob("index.html"):
        assert "Demonstration only." in page.read_text(encoding="utf-8"), page


def test_home_links_the_race(demo_site):
    assert 'href="/races/tx/demo-county/2026-11-03/commissioner-precinct-9/"' in read(demo_site, "index.html")


def test_race_sections_in_required_order(demo_site):
    html = read(demo_site, RACE_PAGE)
    ids = ["office-h", "why-h", "candidates-h", "survey-h", "running-h", "promises-h", "how-h"]
    positions = [html.index(f'id="{i}"') for i in ids]
    assert positions == sorted(positions)


def test_candidates_alphabetical_not_file_order(demo_site):
    html = read(demo_site, RACE_PAGE)
    names = re.findall(r'<h3 id="cand-[^"]+">([^<]+)</h3>', html)
    assert names == ["Avery Example", "Blake Sample", "Casey Placeholder"]


def test_ballot_party_only_when_not_null(demo_site):
    html = read(demo_site, RACE_PAGE)
    assert "Listed on ballot as: Sample Party" in html
    assert "Listed on ballot as: Other Sample Party" in html
    blake = html[html.index('id="cand-blake-sample"'):html.index('id="cand-casey-placeholder"')]
    assert "Listed on ballot as" not in blake
    assert "Not the incumbent" in blake


def test_most_specific_why_it_matters_wins(demo_site):
    html = read(demo_site, RACE_PAGE)
    assert "The commissioners court sets the county tax rate" in html
    assert "OFFICE-LEVEL" not in html and "LOCALITY-LEVEL" not in html


def demo_facts():
    facts = []
    for file in (DEMO / "data").rglob("candidates/*.yaml"):
        doc = yaml.safe_load(file.read_text(encoding="utf-8"))
        for section in ("summary", "records", "funding", "endorsements"):
            facts += doc.get(section) or []
        for section in (doc.get("running_on") or {}).values():
            facts += section or []
    return facts


def test_every_fact_card_shows_its_verification_badge(demo_site):
    html = read(demo_site, RACE_PAGE)
    facts = demo_facts()
    assert any(f["verification"] == "unverified" for f in facts)
    for fact in facts:
        anchor = "f-" + re.sub(r"[^A-Za-z0-9_-]+", "-", fact["id"]).strip("-")
        card = re.search(rf'<li class="card item fact" id="{anchor}">(.*?)</li>', html, re.S)
        assert card, fact["id"]
        expected = "badge-unverified" if fact["verification"] == "unverified" else "badge-verified"
        assert expected in card.group(1), fact["id"]


def test_running_on_definitions_and_empty_categories(demo_site):
    html = read(demo_site, RACE_PAGE)
    for term in ("Policy proposal", "Attack messaging", "Contested claim"):
        assert f"<dt>{term}</dt>" in html
    running = html[html.index('id="running-h"'):html.index('id="promises-h"')]
    assert running.count("Not found in the sources reviewed.") >= 5


def test_promise_tracker_resolves_promises_and_evidence(demo_site):
    html = read(demo_site, RACE_PAGE)
    promises = html[html.index('id="promises-h"'):html.index('id="how-h"')]
    assert '<span class="status status-kept">Kept</span>' in promises
    assert '<span class="status status-pending">Pending</span>' in promises
    assert "Evidence: Sponsored a road plan" in promises


def test_embedded_race_data_is_safe_json_with_alphabetical_candidates(demo_site):
    html = read(demo_site, RACE_PAGE)
    raw = re.search(r'<script type="application/json" id="race-data">(.*?)</script>', html, re.S).group(1)
    assert "<" not in raw
    import json
    data = json.loads(raw)
    assert [c["name"] for c in data["candidates"]] == ["Avery Example", "Blake Sample", "Casey Placeholder"]
    assert len(data["questions"]) == 5
    assert data["corrections_form_url"] is None


def test_demo_pages_have_no_inline_code_or_third_party_assets(demo_site):
    test_pages_have_no_inline_code_or_third_party_assets(demo_site)


def test_survey_js_never_writes_html_or_inline_styles():
    js = (REPO / "site" / "static" / "js" / "survey.js").read_text(encoding="utf-8")
    js = re.sub(r"/\*.*?\*/|^\s*//.*$", "", js, flags=re.S | re.M)  # ignore comments
    for forbidden in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", ".style",
                      "setAttribute(\"style\"", "localStorage", "sessionStorage", "document.cookie",
                      "fetch(", "XMLHttpRequest", "sendBeacon"):
        assert forbidden not in js, forbidden
