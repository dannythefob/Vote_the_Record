"""Build Harris County precincts.yaml and zips.yaml for one election's ballot.

Usage:
  python src/collectors/states/tx/harris_precincts.py --cache <folder> --scotus-sha256 <hash> \
      --ballot-dir data/states/tx/localities/harris-county/elections/2026-11-03 --out <folder>

  --ballot-dir is only read. Write to a review folder first, then copy the two files into the
  ballot folder (a data/ change, which needs the owner's approval).

Sources (both official, both public):
  - Harris County GIS "VPCTs_2026" voting precinct layer (1,224 precincts effective 2026-01-01),
    with each precinct's commissioner, congressional (plan C2333), State House, State Senate,
    SBOE, and JP/constable districts.
  - U.S. Census Bureau TIGERweb, 2020 ZIP Code Tabulation Areas (ZCTAs), which approximate
    ZIP codes.

precincts.yaml is exact: each precinct's districts come straight from the county layer.
zips.yaml is approximate: both layers are rasterized on a ~110 m grid, and a precinct counts
for a ZIP when it covers at least MIN_SHARE of the ZIP's grid cells inside Harris County.
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
STEP = 0.001      # grid step in degrees (~110 m north-south)
MIN_SHARE = 0.01  # a precinct must cover 1% of a ZIP's in-county cells to count for that ZIP
MIN_CELLS = 5     # ZIPs with fewer in-county cells than this are left out (map-edge slivers)
EVERYWHERE = ["court-of-appeals-1", "court-of-appeals-14"]  # Gov't Code 22.201(b), (o): all of Harris County


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


def areas_for(attrs: dict, on_ballot: set[str]) -> dict[str, str]:
    """District kind -> area slug, for the districts that have a contest on this ballot."""
    cand = {
        "us-house": f"us-house-{int(attrs['USCong_C2333'])}",
        "state-house": f"state-house-{int(attrs['St_Rep_Dis'])}",
        "state-senate": f"state-senate-{int(attrs['St_Sen_Dis'])}",
        "sboe": f"sboe-{int(attrs['SBOE_E2106'])}",
        "commissioner": f"harris-county/commissioner-{int(attrs['Comm__Cour'])}",
        "jp": f"harris-county/jp-{int(attrs['JP_Constab'])}",
    }
    return {k: v for k, v in cand.items() if v in on_ballot}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def source(fid, headline, statement, url, title, kind, digest, notes):
    return {"id": fid, "headline": headline, "statement": statement, "label": "official_record",
            "claim_status": "documented", "contradicted_by": [], "source_url": url, "source_title": title,
            "source_kind": kind, "sha256": digest, "archive_url": None, "event_date": TODAY,
            "retrieved": TODAY, "verification": "unverified", "verified_on": None, "reviewer": None,
            "notes": notes}


TODAY = dt.date.today().isoformat()


class _Dumper(yaml.SafeDumper):
    pass


_Dumper.add_representer(type(None), lambda d, _: d.represent_scalar("tag:yaml.org,2002:null", "null"))


def write(path: Path, comment: str, sources: list, key: str, table: dict) -> None:
    """Sources in block style; one line per precinct or ZIP, with its areas as a flow list."""
    text = "# Generated by src/collectors/states/tx/harris_precincts.py. Unverified.\n# " + comment + "\n"
    text += yaml.dump({"sources": sources}, Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=10000)
    text += f"everywhere: {json.dumps(EVERYWHERE)}\n{key}:\n"
    text += "".join(f"  '{k}': {json.dumps(v)}\n" for k, v in table.items())
    yaml.safe_load(text)  # must parse
    path.write_text(text, encoding="utf-8", newline="\n")  # same bytes on every OS


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cache", type=Path, required=True, help="folder for raw downloads (outside data/)")
    ap.add_argument("--ballot-dir", type=Path, required=True, help="the ballot folder (holds ballot.yaml); read only")
    ap.add_argument("--out", type=Path, required=True, help="where to write precincts.yaml and zips.yaml")
    ap.add_argument("--scotus-sha256", required=True, help="sha256 of the downloaded Supreme Court order PDF")
    args = ap.parse_args(argv)
    args.cache.mkdir(parents=True, exist_ok=True)
    args.out.mkdir(parents=True, exist_ok=True)
    for name in ("precincts.yaml", "zips.yaml"):
        if (args.out / name).exists():
            raise SystemExit(f"refusing to overwrite {args.out / name}")

    # Areas with a contest on this ballot.
    ballot_dir = args.ballot_dir.resolve()
    repo_states = ballot_dir.parents[4]  # .../data/states
    ballot = yaml.safe_load((ballot_dir / "ballot.yaml").read_text(encoding="utf-8"))
    on_ballot = set()
    for contest in ballot["contests"]:
        race = yaml.safe_load((repo_states / contest / "race.yaml").read_text(encoding="utf-8"))
        parts = contest.split("/")
        default = parts[0] if parts[1] == "statewide" else parts[2]
        on_ballot.add(race.get("area") or default)

    print("downloading county precinct layer...", file=sys.stderr)
    pct = paged(COUNTY_LAYER, {"where": "1=1", "outFields": COUNTY_FIELDS, "returnGeometry": "true",
                               "outSR": 4326, "geometryPrecision": 6, "f": "geojson"}, args.cache, "vpct", 200)
    attrs = [f["properties"] for f in pct]
    assert len(attrs) == len({a["VPCT"] for a in attrs}), "duplicate precinct numbers"
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
    rasterize(pct, lambda f: f["properties"]["VPCT"], pgrid, x0, y0, cols, rows)
    rasterize(zcta, lambda f: f["properties"]["ZCTA5"], zgrid, x0, y0, cols, rows)

    counts: dict[str, dict[int, int]] = {}
    for prow, zrow in zip(pgrid, zgrid):
        for p, z in zip(prow, zrow):
            if p and z:
                counts.setdefault(z, {}).setdefault(p, 0)
                counts[z][p] += 1

    by_pct = {a["VPCT"]: areas_for(a, on_ballot) for a in attrs}
    precincts = {str(p): sorted(v.values()) for p, v in sorted(by_pct.items())}
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
        zips[z] = entry

    raw_pct = b"".join((args.cache / f).read_bytes() for f in sorted(p.name for p in args.cache.glob("vpct-*.json")))
    raw_zcta = b"".join((args.cache / f).read_bytes() for f in sorted(p.name for p in args.cache.glob("zcta-*.json")))
    fid = ballot_dir.relative_to(repo_states).as_posix()
    county_src = source(
        f"{fid}/precincts#S-01", "Harris County voting precincts and their districts (2026)",
        "Harris County's GIS layer of voting precincts effective January 1, 2026 (1,224 precincts) lists each "
        "precinct's Commissioners Court precinct, congressional district under plan C2333, State House, State "
        "Senate, State Board of Education, and justice of the peace/constable precinct.",
        COUNTY_ITEM, "Harris County GIS: VPCTs_2026 (Voting Precincts effective 1/1/26)", "page", None,
        f"Read from {COUNTY_LAYER} on {TODAY}; SHA-256 of the downloaded query responses: {sha(raw_pct)}. "
        "Credits: Harris County Commissioners Court, Office of County Administration, and Tax Office. The layer's "
        "license says it is informational and not for resale or redistribution; only precinct numbers and district "
        "numbers derived from it are published here. Voter counts in the layer are not used.")
    scotus_src = source(
        f"{fid}/precincts#S-02", "The 2025 congressional map (plan C2333) is in use for 2026",
        "On December 4, 2025, the U.S. Supreme Court granted Texas's application to stay the November 18, 2025 "
        "district court order that had blocked the new congressional map, allowing it to be used.",
        SCOTUS_ORDER, "Supreme Court of the United States: Abbott v. LULAC, No. 25A608, order of December 4, 2025",
        "document", args.scotus_sha256,
        "This is why precincts use the county layer's USCong_C2333 field rather than USCong_C21.")
    zcta_src = source(
        f"{fid}/zips#S-01", "Census ZIP Code Tabulation Areas (approximate ZIP codes)",
        "The U.S. Census Bureau's TIGERweb service publishes 2020 Census ZIP Code Tabulation Areas, which "
        "approximate U.S. Postal Service ZIP code areas.",
        ZCTA_LAYER, "U.S. Census Bureau TIGERweb: 2020 Census ZIP Code Tabulation Areas", "page", None,
        f"Read on {TODAY}; SHA-256 of the downloaded query responses: {sha(raw_zcta)}. ZIP-to-district links "
        f"were computed by overlaying these areas on the county precinct layer on a {STEP}-degree grid; a "
        f"precinct counts for a ZIP when it covers at least {MIN_SHARE:.0%} of the ZIP's grid cells in Harris "
        "County. Results are approximate; the precinct lookup is exact.")
    zip_county = dict(county_src, id=f"{fid}/zips#S-02")

    write(args.out / "precincts.yaml", "Exact: each precinct's districts from the Harris County precinct layer.",
          [county_src, scotus_src], "precincts", precincts)
    write(args.out / "zips.yaml", "Approximate: a nested list means the ZIP is split between those districts.",
          [zcta_src, zip_county], "zips", zips)
    split = sum(1 for e in zips.values() if any(isinstance(x, list) for x in e))
    print(f"wrote {len(precincts)} precincts and {len(zips)} ZIP codes ({split} with at least one split)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
