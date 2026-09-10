"""An H3 hex grid over Berlin, and the search circle each cell turns into.

Why hexagons rather than the squares a bounding box suggests.  Every cell has
six neighbours at one distance, so "the ring around here" is a single honest
number instead of four edge neighbours and four corner ones at 1.41x the
distance.  For a scoring product that is the whole game: a score is mostly a
statement about a neighbourhood, and a square grid quietly distorts every
neighbourhood it describes.  H3 is also a global, standard index, so a cell id
means the same thing here as in whatever the scores are joined against later.

Google's Nearby Search takes a circle, not a hexagon, so each cell is queried
as the circle that circumscribes it: radius equal to the cell's edge length,
since a regular hexagon's circumradius *is* its edge.  That circle is 1.21x the
cell's area, so neighbouring queries overlap by about a fifth.

That overlap is a feature, not an error, and it is worth being precise about
what the resulting number means.  It is **the count of entities within r metres
of the cell centre** -- a density surface sampled on a hex lattice -- not a
partition of the city into disjoint buckets.  For scoring a location that is
the more useful quantity anyway: what matters at a site is what stands near it,
not which administrative bucket those things were filed under.

City totals stay exact regardless, because Nearby Search returns place ids even
on the free tier and ids deduplicate.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

try:
    import h3
except ImportError as exc:  # pragma: no cover - h3 is a hard dependency
    raise ImportError(
        "allberlin needs the h3 package: pip install h3"
    ) from exc

from .geometry import BERLIN_OUTLINE, contains

# Google returns at most this many places per Nearby Search call, whatever the
# circle holds.  Every sizing decision in this file exists because of it.
MAX_RESULTS_PER_CALL = 20

# A hexagon's circumradius equals its edge length; the margin covers H3's cells
# not being perfectly regular and the projection error in the grid arithmetic.
CIRCUMSCRIBE_MARGIN = 1.02


@dataclass(frozen=True)
class Resolution:
    """One H3 resolution, described in the terms this problem cares about."""

    res: int
    cell_area_km2: float
    edge_m: float

    @property
    def query_radius_m(self) -> float:
        """Radius of the circle sent to Google for a cell at this resolution."""
        return self.edge_m * CIRCUMSCRIBE_MARGIN

    @property
    def query_area_km2(self) -> float:
        """Ground that circle actually covers -- 1.21x the cell."""
        return math.pi * (self.query_radius_m / 1000.0) ** 2

    @property
    def saturating_density(self) -> float:
        """Entities per km2 at which a cell starts hitting the 20-result cap.

        Above this the cell has to be split, which is the only thing that makes
        a census expensive.  Choosing a resolution is choosing to stay below
        this line for the density you expect.
        """
        return MAX_RESULTS_PER_CALL / self.query_area_km2


def resolution(res: int) -> Resolution:
    if not 0 <= res <= 15:
        raise ValueError(f"H3 resolutions run 0-15, got {res}")
    return Resolution(
        res=res,
        cell_area_km2=h3.average_hexagon_area(res, "km^2"),
        edge_m=h3.average_hexagon_edge_length(res, "m"),
    )


def resolution_table(lo: int = 7, hi: int = 11) -> List[Resolution]:
    return [resolution(r) for r in range(lo, hi + 1)]


def berlin_cells(res: int, polygon: Sequence[Tuple[float, float]] = None) -> List[str]:
    """Every H3 cell whose centre falls inside Berlin, at ``res``."""
    poly = h3.LatLngPoly(list(polygon or BERLIN_OUTLINE))
    return sorted(h3.polygon_to_cells(poly, res))


def cell_center(cell: str) -> Tuple[float, float]:
    return h3.cell_to_latlng(cell)


def cell_boundary(cell: str) -> List[Tuple[float, float]]:
    return [tuple(p) for p in h3.cell_to_boundary(cell)]


def cell_query_circle(cell: str) -> Tuple[float, float, float]:
    """The (lat, lng, radius_m) to send to Nearby Search for one cell."""
    lat, lng = h3.cell_to_latlng(cell)
    res = h3.get_resolution(cell)
    return lat, lng, resolution(res).query_radius_m


def ring(cell: str, k: int = 1) -> List[str]:
    """The cells within k steps, the cell itself included.

    This is what a hex grid buys: one distance, six neighbours, no argument
    about whether a diagonal counts.
    """
    return sorted(h3.grid_disk(cell, k))


def children(cell: str) -> List[str]:
    """The seven cells one resolution finer that make up this one.

    Seven, not four: H3's aperture. Used only as the last resort when a single
    Google type saturates a cell, since a child's query circle reaches outside
    its parent and the count stops being exact.
    """
    return sorted(h3.cell_to_children(cell, h3.get_resolution(cell) + 1))


def ring_size(k: int) -> int:
    """Cells in a k-disk: 1, 7, 19, 37, ... = 3k(k+1)+1."""
    return 3 * k * (k + 1) + 1


def cells_in_berlin(cells: Iterable[str]) -> List[str]:
    return [c for c in cells if contains(BERLIN_OUTLINE, *h3.cell_to_latlng(c))]


def recommended_resolution(density_per_km2: float,
                           headroom: float = 0.5) -> int:
    """The coarsest resolution that stays clear of the 20-result cap.

    ``headroom`` is how much of the cap to plan on using.  Half is not timidity:
    density inside a city varies by more than an order of magnitude around its
    mean, so a resolution sized to the mean saturates across the whole centre.
    """
    if density_per_km2 <= 0:
        return 8
    for res in range(6, 13):
        r = resolution(res)
        if density_per_km2 * r.query_area_km2 <= MAX_RESULTS_PER_CALL * headroom:
            return res
    return 12
