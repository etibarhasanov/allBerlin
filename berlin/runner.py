"""Executing the census: one circle per hex cell, split where it saturates.

This is the only module that talks to Google.  It borrows allRestaurants'
Places client for retries, rate limiting and the request budget, and adds the
two things a hex census needs that a bounding-box sweep does not: attribution
of every result to the cell whose circle found it, and place ids kept per cell
so that counts stay exact under the overlap between neighbouring circles.

The stopping rule is the census one -- a query returning a full 20 is hiding
more -- but *how* it is unhidden matters more here than in a bounding-box
sweep, and the obvious answer is wrong.

Splitting a saturated circle into four covering circles, which is what
allRestaurants does, works fine when the target is an area: neighbouring
circles overlap anyway and nothing is attributed to anything. It does not work
when the target is a cell. The four children sit at (+/- r/2, +/- r/2) with
radius r/sqrt(2), so they reach 1.43r from the centre and drag in places from
well outside the cell they are supposed to be measuring. Measured on a test
clump: 75 places returned for a circle holding 62, a 21% over-count. And it
cannot be cleaned up afterwards, because an IDs-Only response carries no
coordinates to filter on.

So saturation is broken by **splitting the type list instead of the circle**.
A cell that returns 20 for thirty retail types is asked again for fifteen of
them, and again for the other fifteen, all against the identical circle. Every
result is still exactly where it was, the union is the complete answer, and the
count stays exact. It is free, so the extra calls cost only time -- and the
subsets are useful in their own right, since they are finer categories.

Only when a *single* type still saturates does geometry have to move, and then
the cell descends to its seven H3 children rather than to four quadrants.
Those cells are flagged as inexact rather than quietly reported alongside the
others.

There is no review bar here and there cannot be one: the IDs-Only response that
makes this free carries no review count. That is fine -- the review bar existed
to keep a *paid* sweep cheap, and nothing here is paid.

Results are written as they arrive and the cell log is checked before each call,
so an interrupted run resumes instead of paying for the same ground twice --
free calls still cost hours.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Set

from . import hexgrid
from .entities import Category

log = logging.getLogger(__name__)

MAX_RESULTS_PER_CALL = hexgrid.MAX_RESULTS_PER_CALL

# How far a cell may descend when even a single type saturates it.  Two levels
# takes a res-9 cell to res 11, a 29 m hexagon, which no single Google type
# fills twenty deep.
MAX_DESCENT = 2


@dataclass
class CensusStats:
    cells_done: int = 0
    cells_skipped: int = 0
    cells_failed: int = 0
    calls: int = 0
    splits: int = 0
    max_depth: int = 0
    entities: int = 0
    # Cells whose count needed the grid to move, and so may over-count.
    inexact_cells: int = 0


class CountStore:
    """Per-cell counts and place ids, in one SQLite file.

    Ids are kept, not just totals, for two reasons.  Neighbouring cells' query
    circles overlap by about a fifth, so a city total taken by adding cell
    counts would double-count the overlap -- with ids it is a set union and
    exact.  And a second run months later can diff against the first, which a
    stored integer cannot support.
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
                    cell TEXT NOT NULL,
                    category TEXT NOT NULL,
                    resolution INTEGER NOT NULL,
                    n INTEGER NOT NULL,
                    calls INTEGER NOT NULL,
                    max_depth INTEGER NOT NULL,
                    exact INTEGER NOT NULL DEFAULT 1,
                    PRIMARY KEY (cell, category)
                )""")
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS cell_places (
                    cell TEXT NOT NULL,
                    category TEXT NOT NULL,
                    place_id TEXT NOT NULL,
                    PRIMARY KEY (cell, category, place_id)
                )""")
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS ix_places_id ON cell_places(place_id)")
            self.conn.commit()

    def is_done(self, cell: str, category: str) -> bool:
        with self._lock:
            row = self.conn.execute(
                "SELECT 1 FROM cell_census WHERE cell=? AND category=?",
                (cell, category)).fetchone()
        return row is not None

    def record(self, cell: str, category: str, res: int, ids: Set[str],
               calls: int, depth: int, exact: bool = True) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO cell_census VALUES (?,?,?,?,?,?,?)",
                (cell, category, res, len(ids), calls, depth, int(exact)))
            self.conn.executemany(
                "INSERT OR IGNORE INTO cell_places VALUES (?,?,?)",
                [(cell, category, pid) for pid in ids])
            self.conn.commit()

    def counts(self, resolution: Optional[int] = None) -> Dict[str, Dict[str, int]]:
        """cell -> category -> count, the shape berlin.scoring wants."""
        sql = "SELECT cell, category, n FROM cell_census"
        params: List = []
        if resolution is not None:
            sql += " WHERE resolution=?"
            params.append(resolution)
        out: Dict[str, Dict[str, int]] = {}
        with self._lock:
            for cell, category, n in self.conn.execute(sql, params):
                out.setdefault(cell, {})[category] = n
        return out

    def unique_entities(self, category: Optional[str] = None) -> int:
        """City total, deduplicated -- what adding up the cells cannot give."""
        sql = "SELECT COUNT(DISTINCT place_id) FROM cell_places"
        params: List = []
        if category:
            sql += " WHERE category=?"
            params.append(category)
        with self._lock:
            return self.conn.execute(sql, params).fetchone()[0]

    def close(self) -> None:
        with self._lock:
            self.conn.close()


class HexCensus:
    """Count one category across a list of H3 cells."""

    def __init__(self, client, store: CountStore, category: Category,
                 resolution: int, workers: int = 5, resume: bool = True,
                 language_code: Optional[str] = None,
                 region_code: Optional[str] = "DE"):
        self.client = client
        self.store = store
        self.category = category
        self.resolution = resolution
        self.workers = max(1, workers)
        self.resume = resume
        self.language_code = language_code
        self.region_code = region_code
        self.stats = CensusStats()
        self._lock = threading.Lock()

    def _search(self, circle, types: Sequence[str]) -> List[dict]:
        return self.client.search_nearby(
            circle,
            included_types=list(types),
            # Distance, not popularity: with no review count to read there is
            # no way to tell a saturated circle's tail is in view, so the only
            # sound rule is "a full 20 means split", and that needs the nearest
            # 20 rather than the most famous 20 -- ranked by popularity the
            # same well-known places come back however small the circle gets.
            rank_preference="DISTANCE",
            language_code=self.language_code,
            region_code=self.region_code,
        )

    def count_cell(self, cell: str) -> Set[str]:
        """Every place id inside one cell's query circle."""
        ids, exact, calls, depth = self._count(cell, self.category.types, 0)
        with self._lock:
            self.stats.calls += calls
            self.stats.max_depth = max(self.stats.max_depth, depth)
            if not exact:
                self.stats.inexact_cells += 1
        self.store.record(cell, self.category.key, self.resolution,
                          ids, calls, depth, exact)
        return ids

    def _count(self, cell: str, types: Sequence[str], descent: int):
        """Ids in ``cell``'s circle for ``types``, splitting types first.

        Returns (ids, exact, calls, deepest_descent).  ``exact`` is False only
        where a single type saturated a cell and the count had to fall back to
        descending the grid, whose child circles reach outside the parent.
        """
        from allrestaurants.geo import Circle

        lat, lng, radius = hexgrid.cell_query_circle(cell)
        circle = Circle(lat, lng, radius, descent)
        ids: Set[str] = set()
        exact = True
        calls = 0
        deepest = descent
        pending: List[List[str]] = [list(types)]

        while pending:
            subset = pending.pop()
            places = self._search(circle, subset)
            calls += 1
            for raw in places:
                pid = raw.get("id") or raw.get("name")
                if pid:
                    ids.add(pid)
            if len(places) < MAX_RESULTS_PER_CALL:
                continue
            with self._lock:
                self.stats.splits += 1
            if len(subset) > 1:
                # Halve the type list against the same circle: exact, free,
                # and the halves are meaningful sub-categories in themselves.
                mid = len(subset) // 2
                pending.append(subset[:mid])
                pending.append(subset[mid:])
                continue
            # One type, still twenty deep. Only now does geometry move.
            if descent >= MAX_DESCENT:
                exact = False
                continue
            for child in hexgrid.children(cell):
                c_ids, c_exact, c_calls, c_depth = self._count(
                    child, subset, descent + 1)
                ids |= c_ids
                exact = False        # child circles reach outside the parent
                calls += c_calls
                deepest = max(deepest, c_depth)
        return ids, exact, calls, deepest

    def _guarded(self, cell: str) -> int:
        if self.resume and self.store.is_done(cell, self.category.key):
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
            self.stats.entities += len(found)
        return len(found)

    def run(self, cells: Sequence[str]) -> CensusStats:
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            list(pool.map(self._guarded, cells))
        return self.stats
