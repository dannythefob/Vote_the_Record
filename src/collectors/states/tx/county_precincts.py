"""Build a Texas county's precincts.yaml and zips.yaml (and lookup outlines) for one election's ballot.

Usage:
  python src/collectors/states/tx/county_precincts.py --county harris-county --cache <folder> \
      --scotus-sha256 <hash> --ballot-dir data/states/tx/localities/harris-county/elections/2026-11-03 --out <folder>

  Counties are configured in COUNTIES below (precinct layer, district fields, local areas).

  --ballot-dir is only read. Write to a review folder first, then copy the two files into the
  ballot folder (a data/ change, which needs the owner's approval).

Sources (all official, all public):
  - The county's voting precinct layer, with each precinct's commissioner, congressional (plan
    C2333), State House, State Senate, SBOE, and JP/constable districts. Harris: "VPCTs_2026"
    (1,224 precincts). Travis: "Election Precincts" (308 precincts, approved December 4, 2025).
  - U.S. Census Bureau TIGERweb, 2020 ZIP Code Tabulation Areas (ZCTAs), which approximate
    ZIP codes.

precincts.yaml is exact: each precinct's districts come straight from the county layer.
zips.yaml is approximate: both layers are rasterized on a ~110 m grid, and a precinct counts
for a ZIP when it covers at least MIN_SHARE of the ZIP's grid cells inside the county.
When a ZIP's precincts fall in different districts of the same kind, those districts are
written as a nested list ("depends on your address").

Only districts with a contest on the ballot are written (e.g. State Senate districts not up
this year are left out). Everything is written unverified; the owner verifies the sources.
The script refuses to overwrite existing files.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import yaml

COUNTY_ITEM = "https://harriscounty.maps.arcgis.com/home/item.html?id=d5a840ea0bf9442e946be10c6d43e658"
COUNTY_LAYER = "https://services.arcgis.com/su8ic9KbA7PYVxPS/arcgis/rest/services/VPCTs_2026/FeatureServer/2"
COUNTY_FIELDS = "VPCT,Comm__Cour,USCong_C2333,St_Rep_Dis,St_Sen_Dis,SBOE_E2106,JP_Constab"
ZCTA_LAYER = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/tigerWMS_Current/MapServer/2"
SCOTUS_ORDER = "https://www.supremecourt.gov/opinions/25pdf/25a608_7khn.pdf"
TIGER_SERVICE = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/tigerWMS_Current/MapServer"
PLACE_LAYER = TIGER_SERVICE + "/28"   # Incorporated Places (cities)
SCHOOL_LAYER = TIGER_SERVICE + "/14"  # Unified School Districts
TCEQ_SERVICE = "https://gisweb.tceq.texas.gov/arcgis/rest/services/iwud/WaterDistricts_PRD/MapServer"
TCEQ_FWSD = TCEQ_SERVICE + "/2"   # Fresh Water Supply Districts
TCEQ_MMD = TCEQ_SERVICE + "/5"    # Municipal Management Districts (incl. improvement districts)
TCEQ_MUD = TCEQ_SERVICE + "/6"    # Municipal Utility Districts (TCEQ also files some WCIDs and PUDs here)
TCEQ_WCID = TCEQ_SERVICE + "/13"  # Water Control & Improvement Districts

HARRIS_LOCAL_AREAS = {
    "city-of-houston": (PLACE_LAYER, "4835000"),
    "city-of-baytown": (PLACE_LAYER, "4806128"),
    "city-of-league-city": (PLACE_LAYER, "4841980"),
    "channelview-isd": (SCHOOL_LAYER, "4813590"),
    "crosby-isd": (SCHOOL_LAYER, "4815750"),
    "cypress-fairbanks-isd": (SCHOOL_LAYER, "4816110"),
    "huffman-isd": (SCHOOL_LAYER, "4823820"),
    "klein-isd": (SCHOOL_LAYER, "4825740"),
    "la-porte-isd": (SCHOOL_LAYER, "4826190"),
    "new-caney-isd": (SCHOOL_LAYER, "4832400"),
    "sheldon-isd": (SCHOOL_LAYER, "4839990"),
    "spring-isd": (SCHOOL_LAYER, "4841220"),
    "tomball-isd": (SCHOOL_LAYER, "4842960"),
    # TCEQ water districts, matched by DISTRICT_ID.
    "harris-county-fwsd-1a": (TCEQ_FWSD, "3639000"),
    "harris-county-mud-50": (TCEQ_MUD, "3737148"),
    "harris-county-mud-127": (TCEQ_MUD, "3737312"),
    "harris-county-mud-130": (TCEQ_MUD, "3737318"),
    "harris-county-mud-189": (TCEQ_MUD, "3737446"),
    "harris-county-mud-553": (TCEQ_MUD, "9000004"),
    "harris-county-wcid-89": (TCEQ_MUD, "4190000"),
    "intercontinental-crossing-mud": (TCEQ_MUD, "4711250"),
    "spanish-cove-pud": (TCEQ_MUD, "7587000"),
    "west-harris-county-mud-15": (TCEQ_MUD, "8472972"),
    "weston-mud": (TCEQ_MUD, "8474000"),
    "old-town-spring-improvement-district": (TCEQ_MMD, "6205100"),
}
# Local areas: area slug -> (Census layer, GEOID). Only areas with a contest on the ballot are used.
TRAVIS_ITEM = "https://www.arcgis.com/home/item.html?id=e1c2deb0b8394b25ba42ceaba057a8eb"
TRAVIS_LAYER = "https://services1.arcgis.com/HGcSYZ5bvjRswoCb/arcgis/rest/services/Election_Precincts_2025/FeatureServer/0"
TRAVIS_LOCAL_AREAS = {
    "city-of-austin": (PLACE_LAYER, "4805000"),
    "city-of-elgin": (PLACE_LAYER, "4823044"),
    "city-of-jonestown": (PLACE_LAYER, "4838020"),
    "city-of-lago-vista": (PLACE_LAYER, "4840264"),
    "city-of-manor": (PLACE_LAYER, "4846440"),
    "city-of-pflugerville": (PLACE_LAYER, "4857176"),
    "city-of-sunset-valley": (PLACE_LAYER, "4871324"),
    "village-of-volente": (PLACE_LAYER, "4875752"),
    "austin-isd": (SCHOOL_LAYER, "4808940"),
    "coupland-isd": (SCHOOL_LAYER, "4815420"),
    "del-valle-isd": (SCHOOL_LAYER, "4816620"),
    "leander-isd": (SCHOOL_LAYER, "4827030"),
    "manor-isd": (SCHOOL_LAYER, "4828890"),
    "pflugerville-isd": (SCHOOL_LAYER, "4834830"),
    "round-rock-isd": (SCHOOL_LAYER, "4838080"),
    "cypress-ranch-wcid-1": (TCEQ_WCID, "2413100"),
    "hero-way-west-mud": (TCEQ_MUD, "4429750"),
    "kennedy-hill-mud": (TCEQ_MUD, "0630202"),
    "north-austin-mud-1": (TCEQ_MUD, "5968600"),
    "northtown-mud": (TCEQ_MUD, "6013100"),
    "sunfield-mud-2": (TCEQ_MUD, "7632800"),
    "travis-county-wcid-17": (TCEQ_WCID, "7963000"),
    "vista-mud": (TCEQ_MUD, "8325625"),
    "williamson-travis-mud-1": (TCEQ_MUD, "8670000"),
}

# Per county: precinct layer, its field for each district kind, areas every voter shares, local areas.
COUNTIES = {
    "harris-county": {
        "name": "Harris County", "item": COUNTY_ITEM, "layer": COUNTY_LAYER, "precinct_field": "VPCT",
        "fields": {"us-house": "USCong_C2333", "state-house": "St_Rep_Dis", "state-senate": "St_Sen_Dis",
                   "sboe": "SBOE_E2106", "commissioner": "Comm__Cour", "jp": "JP_Constab"},
        "everywhere": ["court-of-appeals-1", "court-of-appeals-14"],  # Gov't Code 22.201(b), (o)
        "local_areas": HARRIS_LOCAL_AREAS,
        "headline": "Harris County voting precincts and their districts (2026)",
        "statement": ("Harris County's GIS layer of voting precincts effective January 1, 2026 (1,224 precincts) lists each "
                      "precinct's Commissioners Court precinct, congressional district under plan C2333, State House, State "
                      "Senate, State Board of Education, and justice of the peace/constable precinct."),
        "title": "Harris County GIS: VPCTs_2026 (Voting Precincts effective 1/1/26)",
        "credits": ("Credits: Harris County Commissioners Court, Office of County Administration, and Tax Office. The layer's "
                    "license says it is informational and not for resale or redistribution; only precinct numbers and district "
                    "numbers derived from it are published here. Voter counts in the layer are not used."),
        "field_note": "This is why precincts use the county layer's USCong_C2333 field rather than USCong_C21.",
    },
    "travis-county": {
        "name": "Travis County", "item": TRAVIS_ITEM, "layer": TRAVIS_LAYER, "precinct_field": "Precinct",
        "fields": {"us-house": "Congressional", "state-house": "Legislative", "state-senate": "Senate",
                   "sboe": "StateBoardOfEducation", "commissioner": "Commissioner", "jp": "JPConstable"},
        "everywhere": ["court-of-appeals-3"],  # Gov't Code 22.201(d)
        "local_areas": TRAVIS_LOCAL_AREAS,
        "headline": "Travis County election precincts and their districts (2026)",
        "statement": ("Travis County's GIS layer of election precincts, approved by the Commissioners Court on December 4, "
                      "2025 and drawn for congressional plan C2333 (308 precincts), lists each precinct's congressional "
                      "district, State Senate and State House districts, Commissioners Court precinct, justice of the "
                      "peace/constable precinct, and State Board of Education district."),
        "title": "Travis County GIS: Election Precincts (approved by Commissioners Court December 4, 2025)",
        "credits": "Voter counts in the layer are not used.",
        "field_note": "The Travis County layer's Congressional field follows plan C2333 (see the layer's item description).",
    },
}

# Wayback Machine copies, checked when made (documents: same SHA-256 as the original).
ARCHIVES = {
    SCOTUS_ORDER: "https://web.archive.org/web/20260930221333/https://www.supremecourt.gov/opinions/25pdf/25a608_7khn.pdf",
    ZCTA_LAYER: "https://web.archive.org/web/20260930221535/" + ZCTA_LAYER,
    PLACE_LAYER: "https://web.archive.org/web/20260930221613/" + PLACE_LAYER,
    TIGER_SERVICE: "https://web.archive.org/web/20260930223321/" + TIGER_SERVICE,
    TCEQ_SERVICE: "https://web.archive.org/web/20260930225735/" + TCEQ_SERVICE,
}
SURE_SHARE = 0.99  # a precinct or ZIP at least this much inside an area is treated as fully inside
STEP = 0.001      # grid step in degrees (~110 m north-south)
MIN_SHARE = 0.01  # a precinct must cover 1% of a ZIP's in-county cells to count for that ZIP
MIN_CELLS = 5     # ZIPs with fewer in-county cells than this are left out (map-edge slivers)
SIMPLIFY = 0.00002  # precinct outlines for the address lookup: ~2 m Douglas-Peucker tolerance


def fetch(url: str, params: dict, cache: Path, name: str) -> bytes:
    path = cache / name
    if path.exists():
        return path.read_bytes()
    full = f"{url}/query?{urllib.parse.urlencode(params)}"
    for attempt in range(6):
        try:
            with urllib.request.urlopen(urllib.request.Request(full, headers={"User-Agent": "vote-the-record"}),
                                        timeout=180) as r:
                data = r.read()
            json.loads(data)
            path.write_bytes(data)
            return data
        except Exception as exc:  # network resets happen; retry with backoff
            print(f"  retry {attempt + 1} for {name}: {exc}", file=sys.stderr)
            time.sleep(3 * (attempt + 1))
    raise SystemExit(f"could not download {name}")


def paged(url: str, base: dict, cache: Path, prefix: str, page: int) -> list[dict]:
    feats, offset = [], 0
    while True:
        data = json.loads(fetch(url, {**base, "resultOffset": offset, "resultRecordCount": page},
                                cache, f"{prefix}-{offset}.json"))
        feats += data["features"]
        if not data.get("exceededTransferLimit") and len(data["features"]) < page:
            return feats
        offset += page


def rings(geometry: dict) -> list[list[tuple[float, float]]]:
    polys = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
    return [[(x, y) for x, y, *_ in ring] for poly in polys for ring in poly]


def rasterize(features, key, grid, x0, y0, cols, rows):
    """Even-odd scanline fill of each feature's rings into grid[row][col] = key(feature)."""
    for f in features:
        rs = rings(f["geometry"])
        ys = [y for r in rs for _, y in r]
        r_lo = max(0, int((min(ys) - y0) / STEP))
        r_hi = min(rows - 1, int((max(ys) - y0) / STEP) + 1)
        value = key(f)
        for row in range(r_lo, r_hi + 1):
            y = y0 + (row + 0.5) * STEP
            xs = []
            for ring in rs:
                for (xa, ya), (xb, yb) in zip(ring, ring[1:] + ring[:1]):
                    if (ya > y) != (yb > y):
                        xs.append(xa + (y - ya) * (xb - xa) / (yb - ya))
            xs.sort()
            for a, b in zip(xs[0::2], xs[1::2]):
                c_lo = max(0, math.ceil((a - x0) / STEP - 0.5))    # first cell center at or after a
                c_hi = min(cols - 1, math.floor((b - x0) / STEP - 0.5))  # last cell center at or before b
                for col in range(c_lo, c_hi + 1):
                    grid[row][col] = value


def simplify(points: list, tol: float) -> list:
    """Douglas-Peucker line simplification (iterative, keeps the first and last point)."""
    if len(points) < 3:
        return list(points)
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        a, b = stack.pop()
        (x1, y1), (x2, y2) = points[a], points[b]
        dx, dy = x2 - x1, y2 - y1
        length = (dx * dx + dy * dy) ** 0.5
        best, idx = -1.0, a
        for i in range(a + 1, b):
            x0, y0 = points[i]
            d = (abs(dy * x0 - dx * y0 + x2 * y1 - y2 * x1) / length) if length else ((x0 - x1) ** 2 + (y0 - y1) ** 2) ** 0.5
            if d > best:
                best, idx = d, i
        if best > tol:
            keep[idx] = True
            stack += [(a, idx), (idx, b)]
    return [p for p, k in zip(points, keep) if k]


def shapes(features, source_id: str, pid: str = "VPCT") -> dict:
    """Simplified precinct outlines for the in-browser address lookup (even-odd rings)."""
    out = {}
    for f in sorted(features, key=lambda f: f["properties"][pid]):
        rs = []
        for ring in rings(f["geometry"]):
            s = simplify(ring, SIMPLIFY)
            if len(s) >= 4:
                rs.append([[round(x, 5), round(y, 5)] for x, y in s])
        out[str(f["properties"][pid])] = rs
    return {"source": source_id, "note": "Generated by src/collectors/states/tx/county_precincts.py; "
            f"outlines simplified to about {SIMPLIFY} degrees. Unverified.", "precincts": out}


def areas_for(attrs: dict, on_ballot: set[str], county: str = "harris-county") -> dict[str, str]:
    """District kind -> area slug, for the districts that have a contest on this ballot."""
    fields = COUNTIES[county]["fields"]
    num = {kind: int(re.sub(r"\D", "", str(attrs[field]))) for kind, field in fields.items()}
    cand = {
        "us-house": f"us-house-{num['us-house']}",
        "state-house": f"state-house-{num['state-house']}",
        "state-senate": f"state-senate-{num['state-senate']}",
        "sboe": f"sboe-{num['sboe']}",
        "commissioner": f"{county}/commissioner-{num['commissioner']}",
        "jp": f"{county}/jp-{num['jp']}",
    }
    return {k: v for k, v in cand.items() if v in on_ballot}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def source(fid, headline, statement, url, title, kind, digest, notes):
    return {"id": fid, "headline": headline, "statement": statement, "label": "official_record",
            "claim_status": "documented", "contradicted_by": [], "source_url": url, "source_title": title,
            "source_kind": kind, "sha256": digest, "archive_url": ARCHIVES.get(url), "event_date": TODAY,
            "retrieved": TODAY, "verification": "unverified", "verified_on": None, "reviewer": None,
            "notes": notes}


TODAY = dt.date.today().isoformat()


class _Dumper(yaml.SafeDumper):
    pass


_Dumper.add_representer(type(None), lambda d, _: d.represent_scalar("tag:yaml.org,2002:null", "null"))


def write(path: Path, comment: str, sources: list, key: str, table: dict, everywhere: list) -> None:
    """Sources in block style; one line per precinct or ZIP, with its areas as a flow list."""
    text = "# Generated by src/collectors/states/tx/county_precincts.py. Unverified.\n# " + comment + "\n"
    text += yaml.dump({"sources": sources}, Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=10000)
    text += f"everywhere: {json.dumps(everywhere)}\n{key}:\n"
    text += "".join(f"  '{k}': {json.dumps(v)}\n" for k, v in table.items())
    yaml.safe_load(text)  # must parse
    path.write_text(text, encoding="utf-8", newline="\n")  # same bytes on every OS


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--county", required=True, choices=sorted(COUNTIES), help="which county's precinct layer to use")
    ap.add_argument("--cache", type=Path, required=True, help="folder for raw downloads (outside data/)")
    ap.add_argument("--ballot-dir", type=Path, required=True, help="the ballot folder (holds ballot.yaml); read only")
    ap.add_argument("--out", type=Path, required=True, help="where to write precincts.yaml and zips.yaml")
    ap.add_argument("--scotus-sha256", required=True, help="sha256 of the downloaded Supreme Court order PDF")
    ap.add_argument("--today", help="date to record as retrieved (default: today)")
    args = ap.parse_args(argv)
    global TODAY
    TODAY = args.today or TODAY
    cfg = COUNTIES[args.county]
    pid = cfg["precinct_field"]
    args.cache.mkdir(parents=True, exist_ok=True)
    args.out.mkdir(parents=True, exist_ok=True)
    for name in ("precincts.yaml", "zips.yaml", "precinct-shapes.json", "area-shapes.json"):
        if (args.out / name).exists():
            raise SystemExit(f"refusing to overwrite {args.out / name}")

    # Areas with a contest on this ballot.
    ballot_dir = args.ballot_dir.resolve()
    repo_states = ballot_dir.parents[4]  # .../data/states
    ballot = yaml.safe_load((ballot_dir / "ballot.yaml").read_text(encoding="utf-8"))
    on_ballot = set()
    for contest in ballot["contests"]:
        folder = repo_states / contest
        race_file = folder / "race.yaml" if (folder / "race.yaml").is_file() else folder / "measure.yaml"
        race = yaml.safe_load(race_file.read_text(encoding="utf-8"))
        parts = contest.split("/")
        default = parts[0] if parts[1] == "statewide" else parts[2]
        on_ballot.add(race.get("area") or default)

    print("downloading county precinct layer...", file=sys.stderr)
    fields = ",".join([pid, *cfg["fields"].values()])
    pct = paged(cfg["layer"], {"where": "1=1", "outFields": fields, "returnGeometry": "true",
                               "outSR": 4326, "geometryPrecision": 6, "f": "geojson"}, args.cache, "vpct", 200)
    attrs = [f["properties"] for f in pct]
    for f in pct:  # precinct numbers as integers (Travis stores them as text)
        f["properties"][pid] = int(f["properties"][pid])
    assert len(attrs) == len({a[pid] for a in attrs}), "duplicate precinct numbers"
    xs = [x for f in pct for r in rings(f["geometry"]) for x, _ in r]
    ys = [y for f in pct for r in rings(f["geometry"]) for _, y in r]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)

    print("downloading Census ZCTAs...", file=sys.stderr)
    zcta = paged(ZCTA_LAYER, {"where": "1=1", "geometry": f"{x0},{y0},{x1},{y1}", "geometryType": "esriGeometryEnvelope",
                              "inSR": 4326, "spatialRel": "esriSpatialRelIntersects", "outFields": "ZCTA5",
                              "returnGeometry": "true", "outSR": 4326, "geometryPrecision": 6, "f": "geojson"},
                 args.cache, "zcta", 50)

    cols, rows = int((x1 - x0) / STEP) + 1, int((y1 - y0) / STEP) + 1
    print(f"rasterizing {len(pct)} precincts and {len(zcta)} ZCTAs on {cols}x{rows} cells...", file=sys.stderr)
    pgrid = [[0] * cols for _ in range(rows)]
    zgrid = [[None] * cols for _ in range(rows)]
    rasterize(pct, lambda f: f["properties"][pid], pgrid, x0, y0, cols, rows)
    rasterize(zcta, lambda f: f["properties"]["ZCTA5"], zgrid, x0, y0, cols, rows)

    counts: dict[str, dict[int, int]] = {}
    for prow, zrow in zip(pgrid, zgrid):
        for p, z in zip(prow, zrow):
            if p and z:
                counts.setdefault(z, {}).setdefault(p, 0)
                counts[z][p] += 1

    # Local areas (cities): rasterize each outline and measure how much of every precinct and
    # ZIP falls inside it. Mostly inside -> the area; partly inside -> a "maybe" entry.
    local = {slug: spec for slug, spec in cfg["local_areas"].items() if slug in on_ballot}
    local_feats = {}
    for slug, (layer, geoid) in local.items():
        field = "DISTRICT_ID" if layer.startswith(TCEQ_SERVICE) else "GEOID"
        prefix = "tceq" if field == "DISTRICT_ID" else "place"
        feats = paged(layer, {"where": f"{field}='{geoid}'", "outFields": f"{field},NAME", "returnGeometry": "true",
                              "outSR": 4326, "geometryPrecision": 6, "f": "geojson"}, args.cache, f"{prefix}-{geoid}", 10)
        assert feats, f"no boundary found for {slug} ({field} {geoid})"
        # Some districts are stored as several pieces: merge them into one multipolygon.
        polys = []
        for f in feats:
            g = f["geometry"]
            polys += [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
        local_feats[slug] = {"type": "Feature", "properties": {}, "geometry": {"type": "MultiPolygon", "coordinates": polys}}
    pct_cells: dict[int, int] = {}
    zip_cells: dict[str, int] = {}
    for prow, zrow in zip(pgrid, zgrid):
        for p, z in zip(prow, zrow):
            if p:
                pct_cells[p] = pct_cells.get(p, 0) + 1
                if z:
                    zip_cells[z] = zip_cells.get(z, 0) + 1
    local_pct: dict[int, list] = {}
    local_zip: dict[str, list] = {}
    for slug, feat in sorted(local_feats.items()):
        agrid = [[0] * cols for _ in range(rows)]
        rasterize([feat], lambda f: 1, agrid, x0, y0, cols, rows)
        in_pct: dict[int, int] = {}
        in_zip: dict[str, int] = {}
        for prow, zrow, arow in zip(pgrid, zgrid, agrid):
            for p, z, a in zip(prow, zrow, arow):
                if a and p:
                    in_pct[p] = in_pct.get(p, 0) + 1
                    if z:
                        in_zip[z] = in_zip.get(z, 0) + 1
        area_total = sum(in_pct.values())
        # Partly inside: at least MIN_SHARE of the precinct/ZIP is in the area, or at least MIN_SHARE of the
        # area is in the precinct/ZIP (so small districts are never dropped).
        for p, n in in_pct.items():
            share = n / pct_cells[p]
            if share >= SURE_SHARE:
                local_pct.setdefault(p, []).append(slug)
            elif share >= MIN_SHARE or n / area_total >= MIN_SHARE:
                local_pct.setdefault(p, []).append([slug])
        for z, n in in_zip.items():
            share = n / zip_cells[z]
            if share >= SURE_SHARE:
                local_zip.setdefault(z, []).append(slug)
            elif share >= MIN_SHARE or n / area_total >= MIN_SHARE:
                local_zip.setdefault(z, []).append([slug])

    by_pct = {a[pid]: areas_for(a, on_ballot, args.county) for a in attrs}
    precincts = {str(p): sorted(v.values()) + local_pct.get(p, []) for p, v in sorted(by_pct.items())}
    zips = {}
    for z, per in sorted(counts.items()):
        total = sum(per.values())
        if total < MIN_CELLS:
            continue
        kept = [p for p, n in per.items() if n / total >= MIN_SHARE]
        kinds: dict[str, set[str]] = {}
        for p in kept:
            for kind, area in by_pct[p].items():
                kinds.setdefault(kind, set()).add(area)
        entry = []
        for kind in ("us-house", "state-senate", "state-house", "sboe", "commissioner", "jp"):
            values = sorted(kinds.get(kind, ()))
            if len(values) == 1:
                entry.append(values[0])
            elif values:
                entry.append(values)
        zips[z] = entry + local_zip.get(z, [])

    raw_pct = b"".join((args.cache / f).read_bytes() for f in sorted(p.name for p in args.cache.glob("vpct-*.json")))
    raw_zcta = b"".join((args.cache / f).read_bytes() for f in sorted(p.name for p in args.cache.glob("zcta-*.json")))
    fid = ballot_dir.relative_to(repo_states).as_posix()
    county_src = source(
        f"{fid}/precincts#S-01", cfg["headline"], cfg["statement"], cfg["item"], cfg["title"], "page", None,
        f"Read from {cfg['layer']} on {TODAY}; SHA-256 of the downloaded query responses: {sha(raw_pct)}. "
        + cfg["credits"])
    scotus_src = source(
        f"{fid}/precincts#S-02", "The 2025 congressional map (plan C2333) is in use for 2026",
        "On December 4, 2025, the U.S. Supreme Court granted Texas's application to stay the November 18, 2025 "
        "district court order that had blocked the new congressional map, allowing it to be used.",
        SCOTUS_ORDER, "Supreme Court of the United States: Abbott v. LULAC, No. 25A608, order of December 4, 2025",
        "document", args.scotus_sha256,
        cfg["field_note"])
    zcta_src = source(
        f"{fid}/zips#S-01", "Census ZIP Code Tabulation Areas (approximate ZIP codes)",
        "The U.S. Census Bureau's TIGERweb service publishes 2020 Census ZIP Code Tabulation Areas, which "
        "approximate U.S. Postal Service ZIP code areas.",
        ZCTA_LAYER, "U.S. Census Bureau TIGERweb: 2020 Census ZIP Code Tabulation Areas", "page", None,
        f"Read on {TODAY}; SHA-256 of the downloaded query responses: {sha(raw_zcta)}. ZIP-to-district links "
        f"were computed by overlaying these areas on the county precinct layer on a {STEP}-degree grid; a "
        f"precinct counts for a ZIP when it covers at least {MIN_SHARE:.0%} of the ZIP's grid cells in "
        f"{cfg['name']}. Results are approximate; the precinct lookup is exact.")
    zip_county = dict(county_src, id=f"{fid}/zips#S-02")
    raw_places = b"".join((args.cache / f).read_bytes() for f in sorted(p.name for p in args.cache.glob("place-*.json")))
    raw_tceq = b"".join((args.cache / f).read_bytes() for f in sorted(p.name for p in args.cache.glob("tceq-*.json")))
    tceq_used = {slug: spec for slug, spec in local.items() if spec[0].startswith(TCEQ_SERVICE)}
    place_src = source(
        f"{fid}/precincts#S-03", "Census boundaries of cities and school districts",
        "The U.S. Census Bureau's TIGERweb service publishes the current boundaries of incorporated places (cities) "
        "and unified school districts.",
        TIGER_SERVICE, "U.S. Census Bureau TIGERweb: Incorporated Places (layer 28) and Unified School Districts (layer 14)",
        "page", None,
        f"Read on {TODAY}; SHA-256 of the downloaded query responses: {sha(raw_places)}. Areas used: "
        + ", ".join(f"{slug} (layer {layer.rsplit('/', 1)[1]}, GEOID {geoid})" for slug, (layer, geoid) in sorted(local.items())
                    if not layer.startswith(TCEQ_SERVICE))
        + f". A precinct or ZIP code at least {SURE_SHARE:.0%} inside an area counts as inside it; one at least "
        f"{MIN_SHARE:.0%} inside, or holding at least {MIN_SHARE:.0%} of the area, is marked as depending on the address. "
        "The address lookup uses the outlines directly.")
    zip_place = dict(place_src, id=f"{fid}/zips#S-03")
    tceq_src = source(
        f"{fid}/precincts#S-04", "TCEQ water district boundaries",
        "The Texas Commission on Environmental Quality's Water Districts map service publishes the boundaries of "
        "water districts, including municipal utility districts, fresh water supply districts, and municipal "
        "management districts.",
        TCEQ_SERVICE, "Texas Commission on Environmental Quality: Water Districts map service", "page", None,
        f"Read on {TODAY}; SHA-256 of the downloaded query responses: {sha(raw_tceq)}. Districts used: "
        + ", ".join(f"{slug} (layer {layer.rsplit('/', 1)[1]}, DISTRICT_ID {geoid})" for slug, (layer, geoid) in sorted(tceq_used.items()))
        + ". Same method as the Census boundaries.")
    zip_tceq = dict(tceq_src, id=f"{fid}/zips#S-04")
    if len(local) != len({g for _, g in local.values()}):
        raise SystemExit("two local areas share a GEOID")

    write(args.out / "precincts.yaml", f"Each precinct's districts from the {cfg['name']} precinct layer; a nested "
          "list means the precinct is only partly in those areas (city lines).",
          [county_src, scotus_src] + ([place_src] if local else []) + ([tceq_src] if tceq_used else []), "precincts",
          precincts, cfg["everywhere"])
    write(args.out / "zips.yaml", "Approximate: a nested list means the ZIP is split between those districts.",
          [zcta_src, zip_county] + ([zip_place] if local else []) + ([zip_tceq] if tceq_used else []), "zips", zips,
          cfg["everywhere"])
    if local:
        area_out = {"source": place_src["id"], "note": "Generated by src/collectors/states/tx/county_precincts.py; "
                    f"outlines simplified to about {SIMPLIFY} degrees. Unverified.", "areas": {}}
        for slug, feat in sorted(local_feats.items()):
            rs = []
            for ring in rings(feat["geometry"]):
                s = simplify(ring, SIMPLIFY)
                if len(s) >= 4:
                    rs.append([[round(x, 5), round(y, 5)] for x, y in s])
            area_out["areas"][slug] = rs
        (args.out / "area-shapes.json").write_text(json.dumps(area_out, separators=(",", ":")),
                                                   encoding="utf-8", newline="\n")
    (args.out / "precinct-shapes.json").write_text(
        json.dumps(shapes(pct, county_src["id"], pid), separators=(",", ":")), encoding="utf-8", newline="\n")
    split = sum(1 for e in zips.values() if any(isinstance(x, list) for x in e))
    print(f"wrote {len(precincts)} precincts and {len(zips)} ZIP codes ({split} with at least one split)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
