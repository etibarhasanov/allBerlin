"""Areas: a named centre and radius, and the density of places inside it.

The product question is almost never "the whole city"; it is "this
neighbourhood against that one".  An area here is a circle you name -- a
station, a high street, a site you are weighing -- and everything downstream
is per area: which cells it covers, what a run over just those cells costs,
and, once the run has happened, how dense the places inside it actually are,
in total and by category.

Two densities are reported and they answer different questions.

*Places per km2* is the classic figure and the one to compare areas by: it is
independent of how big a circle you drew.

*Places per cell* is what the scoring profiles see -- the count within a
205 m query circle, on average over the area -- and it is the figure that
says whether the area saturates the API's twenty-result cap and therefore
what it costs to collect.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from . import hexgrid
from .geometry import BERLIN_OUTLINE, contains
from .census import (ALL_POI_FACTOR, CALLS_PER_EXCESS_MULTIPLE,
                     DEFAULT_SCORING_RESOLUTION, cell_densities)
from .entities import CATEGORIES
from .hexgrid import MAX_RESULTS_PER_CALL, resolution
from .pricing import NEARBY_PRO, bill


@dataclass(frozen=True)
class Area:
    name: str
    lat: float
    lng: float
    radius_km: float

    @classmethod
    def parse(cls, text: str) -> "Area":
        """``name:lat,lng:radius_km`` -- e.g. ``Alexanderplatz:52.5219,13.4132:2``."""
        parts = text.split(":")
        if len(parts) != 3:
            raise ValueError(
                f"expected name:lat,lng:radius_km, got {text!r}")
        name, latlng, radius = parts
        lat, lng = (float(x) for x in latlng.split(","))
        r = float(radius)
        if not contains(BERLIN_OUTLINE, lat, lng):
            raise ValueError(f"{name}: {lat},{lng} is not inside Berlin")
        if r <= 0 or r > 25:
            raise ValueError(f"{name}: radius must be 0-25 km, got {r}")
        return cls(name.strip(), lat, lng, r)

    @property
    def area_km2(self) -> float:
        return math.pi * self.radius_km ** 2


def _km(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    return math.hypot((a[0] - b[0]) * 111.32,
                      (a[1] - b[1]) * 111.32 * math.cos(math.radians(a[0])))


def cells_in(area: Area, res: int = DEFAULT_SCORING_RESOLUTION) -> List[str]:
    """The Berlin cells whose centre lies inside the area."""
    return [c for c in hexgrid.berlin_cells(res)
            if _km(hexgrid.cell_center(c), (area.lat, area.lng)) <= area.radius_km]


@dataclass
class AreaPlan:
    area: Area
    res: int
    cells: List[str]
    places: float          # modelled private entities inside
    calls: float
    saturated: int

    @property
    def covered_km2(self) -> float:
        return len(self.cells) * resolution(self.res).cell_area_km2

    @property
    def per_km2(self) -> float:
        return self.places / self.covered_km2 if self.cells else 0.0

    @property
    def per_cell(self) -> float:
        """Average places within one cell's 205 m query circle."""
        return self.per_km2 * resolution(self.res).query_area_km2

    @property
    def usd(self) -> float:
        return self.calls * NEARBY_PRO.usd_per_call


def plan_area(area: Area, res: int = DEFAULT_SCORING_RESOLUTION) -> AreaPlan:
    """Cells, calls and cost for one area, from the modelled surface."""
    all_cells = hexgrid.berlin_cells(res)
    dens = cell_densities(res)
    index = {c: i for i, c in enumerate(all_cells)}
    r = resolution(res)
    cells = cells_in(area, res)
    places = calls = 0.0
    saturated = 0
    for c in cells:
        d = dens[index[c]]
        places += d * r.cell_area_km2
        expected = d * ALL_POI_FACTOR * r.query_area_km2
        calls += 1
        if expected > MAX_RESULTS_PER_CALL:
            saturated += 1
            calls += CALLS_PER_EXCESS_MULTIPLE * (expected / MAX_RESULTS_PER_CALL - 1)
    return AreaPlan(area, res, cells, places, calls, saturated)


def plan_areas(areas: Sequence[Area], res: int = DEFAULT_SCORING_RESOLUTION,
               months: int = 1) -> Dict[str, object]:
    """Every area priced, plus the bill for running them all together.

    Cells shared by two overlapping areas are counted once in the bill: the
    run de-duplicates them, so the bill must too.
    """
    plans = [plan_area(a, res) for a in areas]
    union = set()
    for p in plans:
        union.update(p.cells)
    calls = sum(p.calls for p in plans)
    # Overlap: scale the summed calls by the share of distinct cells.
    total_cells = sum(len(p.cells) for p in plans)
    if total_cells:
        calls *= len(union) / total_cells
    return {
        "plans": plans,
        "distinct_cells": sorted(union),
        "calls": calls,
        "billing": bill(int(round(calls)), NEARBY_PRO, months),
    }


@dataclass
class AreaDensity:
    """What a run actually found inside an area -- measured, not modelled."""

    area: Area
    cells: int
    places: int                       # distinct place ids
    by_category: Dict[str, int]

    @property
    def covered_km2(self) -> float:
        return self.cells * resolution(DEFAULT_SCORING_RESOLUTION).cell_area_km2

    @property
    def per_km2(self) -> float:
        return self.places / self.covered_km2 if self.cells else 0.0


def density_from_store(store, area: Area,
                       res: int = DEFAULT_SCORING_RESOLUTION) -> AreaDensity:
    """Measured density inside an area, from a census database.

    Counts distinct places whose *own coordinates* fall inside the circle --
    which is the point of having coordinates.  A place found by a cell on
    the edge but standing outside the circle is not counted; one standing
    inside but found by a neighbouring cell is.
    """
    cells = set(cells_in(area, res))
    seen: Dict[str, Optional[str]] = {}
    with store._lock:
        rows = store.conn.execute(
            "SELECT place_id, lat, lng, category FROM places").fetchall()
    for pid, lat, lng, category in rows:
        if _km((lat, lng), (area.lat, area.lng)) <= area.radius_km:
            seen[pid] = category
    by_cat: Dict[str, int] = {}
    for category in seen.values():
        key = category or "other"
        by_cat[key] = by_cat.get(key, 0) + 1
    done = {row[0] for row in store.conn.execute("SELECT cell FROM cell_census")}
    return AreaDensity(area, len(cells & done), len(seen), by_cat)
