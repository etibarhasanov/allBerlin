"""Executing the census: one untyped circle per hex cell, quartered where it
saturates, every result kept with its coordinates and its types.

This is the only module that talks to Google.  It borrows allRestaurants'
Places client for retries, rate limiting and the request budget, and asks for
the Pro field mask -- id, name, coordinates, types, primary type, address --
because that is the cheapest tier Nearby Search has, and because coordinates
and a category are what a location product needs beyond the id anyway.

One pass, no type filter.  A request with no ``includedTypes`` returns the
nearest twenty of everything Google indexes inside the circle, and every one
of them says what it is, so the category is read off the response rather than
inferred from which sweep found it.  Twelve typed passes become one.

Saturation -- a full twenty back, so more are hiding -- is broken by quartering
the circle, as allRestaurants does.  Quartering over-reaches: the four children
extend to 1.43r from the parent's centre and would drag in places from outside
the cell.  With coordinates on every result that is a filter, not a flaw: a
result is kept only if it lies inside the cell's own query circle.  The
first version of this module could not do that, because it had no
coordinates, and had to split the type list instead; that machinery is gone.

Results are written as they arrive and the cell log is checked before each
call, so an interrupted run resumes instead of paying for the same ground
twice.  At $32 per 1,000 that is money as well as hours.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Set, Tuple

from . import hexgrid
from .entities import CATEGORIES, Category

log = logging.getLogger(__name__)

MAX_RESULTS_PER_CALL = hexgrid.MAX_RESULTS_PER_CALL

# How far a saturated circle may keep quartering.  Each level divides the
# radius by sqrt(2) * 0.98 = 1.39, so eight levels take a res-9 cell's 205 m
# circle to about 15 m -- a shopping mall's worth of ground, which is the
# densest thing Google will hand back twenty of at once.  Only saturated
# cells ever go this deep, so the ceiling costs nothing where it is not hit.
MAX_DEPTH = 8
MIN_RADIUS_M = 5.0

# Pro-tier fields, and nothing from a dearer tier: one rating in this list
# would re-price every call to Enterprise.
FIELD_MASK = ",".join([
    "places.id", "places.displayName", "places.location", "places.types",
    "places.primaryType", "places.formattedAddress", "places.businessStatus",
])


@dataclass
class CensusStats:
    cells_done: int = 0
    cells_skipped: int = 0
    cells_failed: int = 0
    calls: int = 0
    splits: int = 0
    max_depth: int = 0
    places: int = 0
    # Results returned by a child circle but outside the parent -- clipped.
    clipped: int = 0


# Google type -> the first category in entities.py that lists it.  Order in
# CATEGORIES is therefore a priority: a bakery is food_drink before it is
# retail, because food_drink comes first.
_TYPE_TO_CATEGORY: Dict[str, str] = {}
for _c in CATEGORIES:
    for _t in _c.types:
        _TYPE_TO_CATEGORY.setdefault(_t, _c.key)


def categorise(types: Sequence[str], primary: Optional[str] = None) -> Optional[str]:
    """The category a place belongs to, from Google's own type list.

    The primary type wins if it is one we know; otherwise the first known
    type in the list; otherwise None -- a park, a monument, a bus stop that
    the transport category does not name -- which is kept, and counted as
    "other", because it still occupied one of the twenty slots.
    """
    if primary and primary in _TYPE_TO_CATEGORY:
        return _TYPE_TO_CATEGORY[primary]
    for t in types:
        if t in _TYPE_TO_CATEGORY:
            return _TYPE_TO_CATEGORY[t]
    return None


class CountStore:
    """Every place, with its coordinates and category, keyed by the cell that
    found it -- and a per-cell log so a run can resume.

    Places are stored once per (cell, id).  Neighbouring query circles overlap
    by about a fifth, so a place near a seam is found from two cells and
    stored under both; a city total is a DISTINCT over ids and exact.
    """

    def __init__(self, path: str):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._lock = threading.Lock()
        self._create_schema()

    def _create_schema(self) -> None:
        with self._lock:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS cell_census (
                    cell TEXT PRIMARY KEY,
                    resolution INTEGER NOT NULL,
                    n INTEGER NOT NULL,
                    calls INTEGER NOT NULL,
                    max_depth INTEGER NOT NULL
                )""")
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS places (
                    cell TEXT NOT NULL,
                    place_id TEXT NOT NULL,
                    name TEXT,
                    lat REAL NOT NULL,
                    lng REAL NOT NULL,
                    primary_type TEXT,
                    types TEXT,
                    category TEXT,
                    address TEXT,
                    business_status TEXT,
                    PRIMARY KEY (cell, place_id)
                )""")
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS ix_places_id ON places(place_id)")
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS ix_places_cat ON places(category)")
            self.conn.commit()

    def is_done(self, cell: str) -> bool:
        with self._lock:
            return self.conn.execute(
                "SELECT 1 FROM cell_census WHERE cell=?", (cell,)).fetchone() is not None

    def record(self, cell: str, res: int, places: Dict[str, dict],
               calls: int, depth: int) -> None:
        rows = []
        for pid, p in places.items():
            rows.append((cell, pid, p.get("name"), p["lat"], p["lng"],
                         p.get("primary_type"), ",".join(p.get("types", ())),
                         p.get("category"), p.get("address"), p.get("status")))
        with self._lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO cell_census VALUES (?,?,?,?,?)",
                (cell, res, len(places), calls, depth))
            self.conn.executemany(
                "INSERT OR REPLACE INTO places VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
            self.conn.commit()

    def counts(self, resolution: Optional[int] = None) -> Dict[str, Dict[str, int]]:
        """cell -> category -> count, the shape berlin.scoring wants.

        Uncategorised places come back under "other" so a cell's total is
        still the number of things Google put there.
        """
        sql = ("SELECT p.cell, COALESCE(p.category, 'other'), COUNT(*) "
               "FROM places p JOIN cell_census c ON c.cell = p.cell")
        params: List = []
        if resolution is not None:
            sql += " WHERE c.resolution=?"
            params.append(resolution)
        sql += " GROUP BY p.cell, p.category"
        out: Dict[str, Dict[str, int]] = {}
        with self._lock:
            for cell, category, n in self.conn.execute(sql, params):
                out.setdefault(cell, {})[category] = n
        return out

    def unique_places(self, category: Optional[str] = None) -> int:
        """City total, deduplicated across the seams between cells."""
        sql = "SELECT COUNT(DISTINCT place_id) FROM places"
        params: List = []
        if category:
            sql += " WHERE category=?"
            params.append(category)
        with self._lock:
            return self.conn.execute(sql, params).fetchone()[0]

    def iter_places(self):
        """One row per distinct place, for export."""
        sql = ("SELECT place_id, name, lat, lng, primary_type, types, category, "
               "address, business_status FROM places GROUP BY place_id")
        with self._lock:
            return self.conn.execute(sql).fetchall()

    def close(self) -> None:
        with self._lock:
            self.conn.close()


def _parse(raw: dict) -> Optional[dict]:
    """Flatten one Nearby Search result; None if it has no usable position."""
    pid = raw.get("id") or raw.get("name")
    loc = raw.get("location") or {}
    if not pid or "latitude" not in loc or "longitude" not in loc:
        return None
    types = list(raw.get("types") or [])
    primary = raw.get("primaryType")
    display = raw.get("displayName") or {}
    return {
        "id": pid,
        "name": display.get("text") if isinstance(display, dict) else display,
        "lat": float(loc["latitude"]),
        "lng": float(loc["longitude"]),
        "types": types,
        "primary_type": primary,
        "category": categorise(types, primary),
        "address": raw.get("formattedAddress"),
        "status": raw.get("businessStatus"),
    }


class HexCensus:
    """Count and locate everything across a list of H3 cells, in one pass."""

    def __init__(self, client, store: CountStore, resolution: int,
                 workers: int = 5, resume: bool = True,
                 language_code: Optional[str] = None,
                 region_code: Optional[str] = "DE"):
        self.client = client
        self.store = store
        self.resolution = resolution
        self.workers = max(1, workers)
        self.resume = resume
        self.language_code = language_code
        self.region_code = region_code
        self.stats = CensusStats()
        self._lock = threading.Lock()

    def _search(self, circle) -> List[dict]:
        return self.client.search_nearby(
            circle,
            # No type filter: everything Google has in the circle.
            included_types=(),
            # Distance, not popularity.  The stopping rule is "a full twenty
            # means split", and that only surfaces new places if a smaller
            # circle returns its *nearest* twenty rather than its most famous.
            rank_preference="DISTANCE",
            language_code=self.language_code,
            region_code=self.region_code,
        )

    def count_cell(self, cell: str) -> Dict[str, dict]:
        """Every place inside one cell's query circle, with coordinates."""
        from allrestaurants.geo import Circle, haversine_m

        lat, lng, radius = hexgrid.cell_query_circle(cell)
        found: Dict[str, dict] = {}
        calls = 0
        deepest = 0
        clipped = 0
        queue = [Circle(lat, lng, radius, 0)]
        while queue:
            circle = queue.pop()
            raw_places = self._search(circle)
            calls += 1
            deepest = max(deepest, circle.depth)
            for raw in raw_places:
                p = _parse(raw)
                if p is None:
                    continue
                # A child circle reaches outside the cell; keep only what
                # falls inside the cell's own circle.  This is the whole
                # reason coordinates make the count exact.
                if haversine_m(lat, lng, p["lat"], p["lng"]) > radius:
                    clipped += 1
                    continue
                found[p["id"]] = p
            saturated = len(raw_places) >= MAX_RESULTS_PER_CALL
            if saturated and circle.depth < MAX_DEPTH \
                    and circle.radius_m / 2 >= MIN_RADIUS_M:
                queue.extend(circle.children())
                with self._lock:
                    self.stats.splits += 1
        with self._lock:
            self.stats.calls += calls
            self.stats.clipped += clipped
            self.stats.max_depth = max(self.stats.max_depth, deepest)
        self.store.record(cell, self.resolution, found, calls, deepest)
        return found

    def _guarded(self, cell: str) -> int:
        if self.resume and self.store.is_done(cell):
            with self._lock:
                self.stats.cells_skipped += 1
            return 0
        try:
            found = self.count_cell(cell)
        except Exception as exc:  # one bad cell must not lose the run
            with self._lock:
                self.stats.cells_failed += 1
            log.error("cell %s failed: %s", cell, exc)
            return 0
        with self._lock:
            self.stats.cells_done += 1
            self.stats.places += len(found)
        return len(found)

    def run(self, cells: Sequence[str]) -> CensusStats:
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            list(pool.map(self._guarded, cells))
        return self.stats
