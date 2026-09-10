"""What a full private-entity census of Berlin costs.

The answer turns on one SKU.  Google's **Nearby Search Essentials (IDs Only)**
returns place ids and nothing else, and it is free with no monthly cap.  A
product that needs to know *how many* entities stand near a point, and of what
kind, needs exactly that and nothing else -- so the whole census is free, and
the constraint is wall-clock time rather than money.

That is the opposite of the conclusion for a review-bearing dataset, and the
reason is worth keeping straight.  Collecting ratings makes IDs-Only useless,
because an id carries no review count, so the review bar has nothing to read
and the sweep must run as a census anyway -- and then you pay $20 per 1,000 for
Place Details on every id the census turned up, one place per call.  Counting
skips that second half entirely.  There is nothing to enrich: the count *is*
the product.

The cost model here is therefore not about money.  It is about calls, because
calls are hours, and about which resolution keeps cells under the 20-result cap
so that splitting stays rare.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from . import hexgrid
from .districts import DISTRICTS, District
from .entities import CATEGORIES, PRIVATE_CATEGORIES, Category
from .hexgrid import MAX_RESULTS_PER_CALL, Resolution, resolution
from .pricing import NEARBY_IDS, NEARBY_PRO, Sku, bill

# Berlin has roughly 190,000 registered companies.  Not all of them are a place
# on a map: holding companies, freelancers registered at home addresses and
# trades working out of a van have no storefront for Google to index.  Taking
# about 63% as mappable gives the planning figure.
BERLIN_REGISTERED_COMPANIES = 190_000
MAPPABLE_SHARE = 0.63
BERLIN_PRIVATE_ENTITIES = int(BERLIN_REGISTERED_COMPANIES * MAPPABLE_SHARE)

# Commercial activity per resident, against the city average.  Flatter than the
# gastronomy spread in districts.py -- a hairdresser and a plumber follow
# residents far more closely than a restaurant follows tourists.
COMMERCIAL_INTENSITY: Dict[str, float] = {
    "Mitte": 2.2,
    "Friedrichshain-Kreuzberg": 1.5,
    "Pankow": 0.9,
    "Charlottenburg-Wilmersdorf": 1.5,
    "Spandau": 0.75,
    "Steglitz-Zehlendorf": 0.9,
    "Tempelhof-Schoeneberg": 1.0,
    "Neukoelln": 0.95,
    "Treptow-Koepenick": 0.8,
    "Marzahn-Hellersdorf": 0.6,
    "Lichtenberg": 0.8,
    "Reinickendorf": 0.75,
}

# Google's default Places quota.  Raisable on request, but plan on it.
DEFAULT_QPS = 10.0

# A category the model has no share for -- an anchor set like transport or
# schools -- is treated as this fraction of all entities for sizing purposes.
ANCHOR_SHARE = 0.02

# A cell over the 20-result cap is resolved by halving its type list against
# the same circle, not by moving the circle -- see runner.py for why.  Measured
# by running that splitter against clumps from 1.2x to 15x the cap, the extra
# calls come out linear in how far over the cap the cell is:
#
#     over the cap   1.2x  2.0x  3.0x  4.5x  7.0x  10x  15x
#     extra calls       2     4     6    14    20   30   58
#
# which is 3.75 extra calls per multiple of the cap, and every one of those
# runs returned the exact count.
CALLS_PER_EXCESS_MULTIPLE = 3.75


def entities_in(district: District) -> float:
    """Mappable private entities expected in one borough."""
    weighted = sum(d.population * COMMERCIAL_INTENSITY[d.name] for d in DISTRICTS)
    share = district.population * COMMERCIAL_INTENSITY[district.name] / weighted
    return BERLIN_PRIVATE_ENTITIES * share


def total_entities() -> float:
    return sum(entities_in(d) for d in DISTRICTS)


def settled_density(district: District) -> float:
    """Entities per km2 of the borough's built-up ground."""
    return entities_in(district) / district.settled_km2


@dataclass
class CategoryPass:
    """One sweep of the city for one category, at one resolution."""

    category: Category
    res: int
    cells: int
    saturated_cells: int
    calls: float
    entities: float

    @property
    def split_calls(self) -> float:
        return self.calls - self.cells

    @property
    def hours(self) -> float:
        return self.calls / DEFAULT_QPS / 3600.0


@dataclass
class CensusPlan:
    """A costed plan for counting every private entity in Berlin."""

    passes: List[CategoryPass]
    res: int
    sku: Sku
    cells: int

    @property
    def calls(self) -> float:
        return sum(p.calls for p in self.passes)

    @property
    def entities(self) -> float:
        return sum(p.entities for p in self.passes if p.category.private)

    @property
    def hours(self) -> float:
        return self.calls / DEFAULT_QPS / 3600.0

    @property
    def saturated_cells(self) -> int:
        return sum(p.saturated_cells for p in self.passes)

    def billing(self) -> Dict[str, float]:
        return bill(int(round(self.calls)), self.sku)


_DENSITY_CACHE: Dict[int, List[float]] = {}

# What a cell outside every borough's built-up rectangle is assumed to hold
# against one inside: a marina, a forest cafe, a garden centre.  Not zero.
UNBUILT_DENSITY_RATIO = 0.1

# A borough-uniform surface has no hotspots, and a surface with no hotspots
# predicts no splitting -- which would be a modelling artefact reported as a
# finding.  Commercial density in a city falls off from the centre far faster
# than borough averages suggest: Friedrichstrasse is not Wedding, and both are
# Mitte.  This is the standard monocentric gradient, a peak multiplier over a
# decay length, applied on top of the borough level and then normalised away
# at the city total so it redistributes rather than inflates.
CENTRE = (52.5200, 13.4050)          # Alexanderplatz, near enough
GRADIENT_PEAK = 3.0                  # 4x the borough mean at the centre
GRADIENT_DECAY_KM = 4.0


def cell_densities(res: int) -> List[float]:
    """Cached, because a res-10 grid is 71,000 point-in-rectangle tests."""
    if res not in _DENSITY_CACHE:
        _DENSITY_CACHE[res] = _cell_densities(res)
    return _DENSITY_CACHE[res]


def _cell_densities(res: int) -> List[float]:
    """Expected entity density at every Berlin cell, entities per km2.

    Each cell takes the density of the borough it falls in, at full strength if
    its centre lands in one of that borough's built-up rectangles and at
    UNBUILT_DENSITY_RATIO otherwise.

    The surface is then scaled so that integrating it over the grid returns
    exactly BERLIN_PRIVATE_ENTITIES.  Without that step the shape of the
    rectangles quietly sets the total -- they cover 645 km2 against 485 km2 of
    genuinely built-up ground, so an unscaled surface reports a third more
    entities than the model actually claims exist, and every count downstream
    inherits the error.
    """
    cells = hexgrid.berlin_cells(res)
    cell_area = resolution(res).cell_area_km2
    raw = []
    for cell in cells:
        lat, lng = hexgrid.cell_center(cell)
        district = _district_at(lat, lng)
        density = entities_in(district) / district.swept_km2
        in_built_up = any(s <= lat <= n and w <= lng <= e
                          for s, w, n, e in district.tiles)
        if not in_built_up:
            density *= UNBUILT_DENSITY_RATIO
        raw.append(density * centre_gradient(lat, lng))
    integral = sum(raw) * cell_area
    if integral <= 0:
        return raw
    scale = BERLIN_PRIVATE_ENTITIES / integral
    return [d * scale for d in raw]


def centre_gradient(lat: float, lng: float) -> float:
    """How much denser than its borough's average a point is, by distance in."""
    d_km = math.hypot((lat - CENTRE[0]) * 111.32,
                      (lng - CENTRE[1]) * 111.32 * 0.6087)
    return 1.0 + GRADIENT_PEAK * math.exp(-d_km / GRADIENT_DECAY_KM)


def _district_at(lat: float, lng: float) -> District:
    """The borough a point belongs to: its own rectangle, else the nearest."""
    for d in DISTRICTS:
        for south, west, north, east in d.tiles:
            if south <= lat <= north and west <= lng <= east:
                return d
    return min(DISTRICTS, key=lambda d: (d.center[0] - lat) ** 2
               + ((d.center[1] - lng) * 0.61) ** 2)


# The resolution is a product decision, not a cost optimisation.  Minimising
# calls alone would pick res 8 every time -- splitting a saturated cell is
# cheaper than laying seven cells where one would do -- but a split does not
# make the grid finer.  Everything a split finds is still attributed to the
# cell it was splitting, so res 8 buys 0.74 km2 granularity however much it
# splits, and 0.74 km2 is a neighbourhood, not a site.
#
#   res 8   531 m edge, 0.74 km2   a district-level view
#   res 9   201 m edge, 0.11 km2   a five-minute walk -- the scoring default
#   res 10   76 m edge, 0.015 km2  a block, for siting a specific door
#
DEFAULT_SCORING_RESOLUTION = 9
CANDIDATE_RESOLUTIONS = (8, 9, 10)


def cost_pass(category: Category, res: int) -> CategoryPass:
    """Calls to sweep the whole city for one category at one resolution."""
    r = resolution(res)
    share = category.share if category.private else ANCHOR_SHARE
    saturated = 0
    calls = 0.0
    entities = 0.0
    for density in cell_densities(res):
        expected = density * share * r.query_area_km2
        entities += density * share * r.cell_area_km2
        calls += 1
        if expected > MAX_RESULTS_PER_CALL:
            saturated += 1
            excess = expected / MAX_RESULTS_PER_CALL - 1.0
            calls += CALLS_PER_EXCESS_MULTIPLE * excess
    return CategoryPass(category, res, len(cell_densities(res)), saturated,
                        calls, entities)


def plan_census(res: Optional[int] = None,
                categories: Optional[Sequence[Category]] = None,
                sku: Sku = NEARBY_IDS) -> CensusPlan:
    """Cost a category-by-category census of Berlin.

    Every category is swept at the same resolution, because that resolution is
    the granularity of the product and the categories have to line up cell for
    cell to be compared within one.
    """
    cats = list(categories or CATEGORIES)
    res = DEFAULT_SCORING_RESOLUTION if res is None else res
    passes = [cost_pass(category, res) for category in cats]
    return CensusPlan(passes, res, sku, len(cell_densities(res)))


def enrichment_cost(entities: float, calls: float) -> Dict[str, float]:
    """What the same sweep would cost if you wanted more than a count.

    Two ways to spend money on this, and they are very different sizes.  The
    cheaper is to re-run the sweep at Pro, which returns name, address,
    location and types twenty at a time.  The other is Place Details on every
    id afterwards, one place per call, which is what you are forced into if the
    sweep itself was IDs-only and you change your mind later.
    """
    from .pricing import DETAILS_PRO

    return {
        "sweep_at_pro_usd": bill(int(round(calls)), NEARBY_PRO)["usd"],
        "details_sku": DETAILS_PRO.name,
        "details_per_entity_usd": bill(int(round(entities)), DETAILS_PRO)["usd"],
        "entities": entities,
        "calls": calls,
    }


def modelled_counts(res: int = DEFAULT_SCORING_RESOLUTION) -> Dict[str, Dict[str, float]]:
    """The count surface the model predicts, for trying the pipeline dry.

    This is **modelled, not measured**.  It exists so the grid, the features
    and the scoring profiles can be exercised end to end before an API key is
    involved, and so a reviewer can see the shape of the output rather than a
    promise of it.  It is smooth by construction -- borough density times a
    distance-to-centre gradient -- and deliberately not roughened with
    plausible-looking noise, because a surface that looked like data would
    invite being used as data.  Real counts have street-level structure this
    cannot show.
    """
    cells = hexgrid.berlin_cells(res)
    densities = cell_densities(res)
    area = resolution(res).query_area_km2
    out: Dict[str, Dict[str, float]] = {}
    for cell, density in zip(cells, densities):
        out[cell] = {
            c.key: density * (c.share if c.private else ANCHOR_SHARE) * area
            for c in CATEGORIES
        }
    return out


def modelled_population(res: int = DEFAULT_SCORING_RESOLUTION) -> Dict[str, float]:
    """Residents per cell, flat within each borough.

    Flat on purpose: residents are far less centralised than businesses, and
    applying the commercial gradient to them would manufacture a correlation
    between demand and supply that the underserved profile exists to look for.
    """
    cells = hexgrid.berlin_cells(res)
    cell_area = resolution(res).cell_area_km2
    out = {}
    for cell in cells:
        lat, lng = hexgrid.cell_center(cell)
        district = _district_at(lat, lng)
        out[cell] = district.population / district.settled_km2 * cell_area
    return out
