"""Core logic of the Harris precinct/ZIP collector (no network)."""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src" / "collectors" / "states" / "tx"))
import harris_precincts as h  # noqa: E402


def square(x0, y0, size, value):
    ring = [[x0, y0], [x0 + size, y0], [x0 + size, y0 + size], [x0, y0 + size], [x0, y0]]
    return {"geometry": {"type": "Polygon", "coordinates": [ring]}, "properties": {"v": value}}


def test_rasterize_fills_cell_centers_inside_the_polygon_only():
    rows = cols = 10
    grid = [[0] * cols for _ in range(rows)]
    h.rasterize([square(0.002, 0.003, 0.004, 7)], lambda f: f["properties"]["v"], grid, 0.0, 0.0, cols, rows)
    filled = {(r, c) for r in range(rows) for c in range(cols) if grid[r][c] == 7}
    assert filled == {(r, c) for r in range(3, 7) for c in range(2, 6)}


def test_rasterize_leaves_holes_empty():
    outer = [[0, 0], [0.006, 0], [0.006, 0.006], [0, 0.006], [0, 0]]
    hole = [[0.002, 0.002], [0.004, 0.002], [0.004, 0.004], [0.002, 0.004], [0.002, 0.002]]
    feature = {"geometry": {"type": "Polygon", "coordinates": [outer, hole]}, "properties": {}}
    grid = [[0] * 6 for _ in range(6)]
    h.rasterize([feature], lambda f: 1, grid, 0.0, 0.0, 6, 6)
    assert grid[3][3] == 0 and grid[0][0] == 1 and grid[5][5] == 1


def test_areas_for_keeps_only_districts_with_a_contest_on_the_ballot():
    attrs = {"USCong_C2333": "07", "St_Rep_Dis": 134, "St_Sen_Dis": 17, "SBOE_E2106": "04",
             "Comm__Cour": 1, "JP_Constab": 1}
    on_ballot = {"us-house-7", "state-house-134", "state-senate-13", "sboe-4",
                 "harris-county/commissioner-2", "harris-county/jp-1"}
    assert h.areas_for(attrs, on_ballot) == {"us-house": "us-house-7", "state-house": "state-house-134",
                                             "sboe": "sboe-4", "jp": "harris-county/jp-1"}
