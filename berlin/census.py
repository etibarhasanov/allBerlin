"""What a full private-entity census of Berlin costs -- with coordinates and a
category for every entity, not just a count.

The first version of this file priced the census at $0 on the free
"Nearby Search IDs-Only" tier.  There is no such tier.  Text Search and Place
Details each have a free IDs-Only SKU; Nearby Search does not, and a Nearby
Search request billing on nothing but ``places.id`` is billed at Pro, $32 per
1,000.  The correction is recorded here rather than tidied away because the
mistake is an easy one to make again.

It turns out to change less than it looks.  Pro is the tier that carries
``location`` and ``types``, and those are the two fields a location product
actually needs beyond the id.  Once you are paying for them, two things happen:

* **Category comes back with every place**, so the twelve typed passes
  collapse into one untyped pass over the whole city.  A single request per
  cell, no ``includedTypes`` at all, returns the nearest twenty of everything
  and each one says what it is.
* **Coordinates make geometric splitting exact.**  A saturated cell can be
  quartered and its results clipped to the cell's own circle, which the
  IDs-only design could not do and had to work around by splitting the type
  list instead.

So the paid census is one pass, about a fifth of the calls the free one would
have taken, and it delivers the richer dataset.  The cheapest route to the
same fields is a two-stage one -- free Text Search discovery, then Place
Details Essentials at $5 per 1,000 with 10,000 free a month -- and it is
priced here too, with the caveat that Text Search is a search rather than an
enumeration and has to be checked against Nearby Search on a few cells before
being trusted for a census.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from . import hexgrid
from .districts import DISTRICTS, District
from .entities import CATEGORIES, PRIVATE_CATEGORIES, Category
from .hexgrid import MAX_RESULTS_PER_CALL, Resolution, resolution
from .pricing import (DETAILS_ESSENTIALS, NEARBY_PRO, TEXT_IDS, Sku, bill,
                      FREE_TRIAL_USD)

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

# An untyped Nearby Search returns every kind of place Google indexes, not just
# private entities: bus stops, parks, ATMs, churches, monuments.  They count
# against the 20-result cap like anything else, so the untyped pass sees more
# density than the private-entity total suggests.  Estimated; the first fifty
# cells of a real run will say what it actually is.
ALL_POI_FACTOR = 1.35

# A saturated cell is quartered into four covering circles and each result is
# kept only if it falls inside the parent's own circle -- exact, now that
# results carry coordinates.  Measured on the allRestaurants fixture, a
# saturated circle costs about 4.4 further calls per multiple of the cap
# before its children come back under it; a little more than the 3.75 the
# type-splitting route cost, because four quadrants overlap one another where
# two halves of a type list did not.
CALLS_PER_EXCESS_MULTIPLE = 4.4



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
    months: int = 1

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
        return bill(int(round(self.calls)), self.sku, self.months)


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

# Borough densities applied cell by cell leave hard rectangular edges wherever
# two boroughs meet, and those edges are an artefact of the rectangles in
# districts.py rather than anything true about Berlin -- commercial density is
# continuous, and a shop does not notice a borough boundary.  Smoothing over
# the 2-ring removes the artefact without moving the total, which is
# renormalised afterwards either way.  Weights fall off by ring distance.
SMOOTHING_RINGS = 2
SMOOTHING_WEIGHTS = (1.0, 0.6, 0.3)


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
    raw = _smooth(cells, raw)
    integral = sum(raw) * cell_area
    if integral <= 0:
        return raw
    scale = BERLIN_PRIVATE_ENTITIES / integral
    return [d * scale for d in raw]


def _smooth(cells: Sequence[str], values: Sequence[float]) -> List[float]:
    """Average each cell over its k-ring, weighted by ring distance.

    Which is a use for the hex grid beyond indexing: a k-ring is one distance
    in every direction, so a hex smooth has no preferred axis.  The same
    operation on a square grid pulls along the diagonals.
    """
    index = {cell: i for i, cell in enumerate(cells)}
    out = []
    for cell in cells:
        total = weight_sum = 0.0
        inner = set()
        for k in range(SMOOTHING_RINGS + 1):
            weight = SMOOTHING_WEIGHTS[k]
            disk = set(hexgrid.ring(cell, k))
            for neighbour in disk - inner:          # the k-th ring alone
                j = index.get(neighbour)
                if j is None:                       # outside Berlin
                    continue
                total += values[j] * weight
                weight_sum += weight
            inner = disk
        out.append(total / weight_sum if weight_sum else 0.0)
    return out


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


def cost_pass(category: Optional[Category], res: int) -> CategoryPass:
    """Calls to sweep the whole city at one resolution.

    With ``category`` None this is the untyped pass -- one request per cell for
    everything Google has there, which is how a Pro sweep is run.  With a
    category it is the old typed pass, kept for sizing a Text Search
    discovery, where each query names one type.
    """
    r = resolution(res)
    if category is None:
        share = ALL_POI_FACTOR
    else:
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
    if category is None:
        # Report the private-entity total, not the all-POI total the pass
        # actually sees -- that is the figure the product is about.
        entities /= ALL_POI_FACTOR
    label = category if category is not None else UNTYPED
    return CategoryPass(label, res, len(cell_densities(res)), saturated,
                        calls, entities)


# Stands in for "no type filter" in a CategoryPass, so the plan can be printed
# with the same code whether it is one untyped pass or twelve typed ones.
UNTYPED = Category("all", "Everything Google indexes", 1.0, ["*"], private=True,
                   note="One untyped request per cell.")


def plan_census(res: Optional[int] = None,
                categories: Optional[Sequence[Category]] = None,
                sku: Sku = NEARBY_PRO, months: int = 1) -> CensusPlan:
    """Cost a Nearby Search Pro census of Berlin: one untyped pass.

    Pass ``categories`` to cost the older typed design instead -- one pass per
    category -- which is what a Text Search discovery would have to do, since
    a Text Search query filters on a single type.
    """
    res = DEFAULT_SCORING_RESOLUTION if res is None else res
    if categories:
        passes = [cost_pass(c, res) for c in categories]
    else:
        passes = [cost_pass(None, res)]
    return CensusPlan(passes, res, sku, len(cell_densities(res)), months)


def two_stage_cost(entities: float, res: Optional[int] = None,
                   months: int = 1) -> Dict[str, float]:
    """The cheapest route to the same fields, and what it depends on.

    Stage one discovers ids with Text Search on its free IDs-Only tier: one
    query per cell per category, each paged up to three times.  Stage two
    buys coordinates and types for every id with Place Details Essentials, at
    $5 per 1,000 and 10,000 free each month -- so a 120,000-entity city is
    about $550 in one month, or nothing at all spread over a year.

    The dependency is stage one.  Text Search is a search, ranked against a
    query string; nothing guarantees it enumerates a rectangle the way Nearby
    Search enumerates a circle.  Before trusting it for a census, run both
    over the same fifty cells and compare the id sets.  If Text Search finds
    what Nearby finds, this route is a fifth of the price.  If it does not,
    the saving was never real.
    """
    res = DEFAULT_SCORING_RESOLUTION if res is None else res
    typed = plan_census(res=res, categories=CATEGORIES, sku=TEXT_IDS)
    # Each Text Search query pages up to three times before it is exhausted;
    # most cells need one page, saturated ones need all three.
    discovery_calls = typed.calls + 2 * typed.saturated_cells
    details = bill(int(round(entities)), DETAILS_ESSENTIALS, months=months)
    return {
        "discovery_sku": TEXT_IDS.name,
        "discovery_calls": discovery_calls,
        "discovery_hours": discovery_calls / DEFAULT_QPS / 3600.0,
        "discovery_usd": 0.0,
        "details_sku": DETAILS_ESSENTIALS.name,
        "details_calls": details["calls"],
        "details_free_calls": details["free_calls"],
        "details_usd": details["usd"],
        "months_to_be_free": math.ceil(entities / DETAILS_ESSENTIALS.free_calls_per_month),
        "total_usd": details["usd"],
    }


def enrichment_cost(entities: float, calls: float) -> Dict[str, float]:
    """What the fields a Pro sweep does not carry would cost on top.

    Ratings and review counts are Enterprise, and there are two ways to add
    them: re-run the sweep at Enterprise ($35 per 1,000, +$3 on every call) or
    fetch Place Details Enterprise for each id afterwards ($20 per 1,000, one
    place per call).  Which is cheaper depends only on how many places a call
    found on average -- past about 0.6 places per call the sweep wins.
    """
    from .pricing import DETAILS_ENTERPRISE, NEARBY_ENTERPRISE

    sweep = bill(int(round(calls)), NEARBY_ENTERPRISE)["usd"] \
        - bill(int(round(calls)), NEARBY_PRO)["usd"]
    return {
        "resweep_at_enterprise_extra_usd": max(0.0, sweep),
        "details_enterprise_usd": bill(int(round(entities)), DETAILS_ENTERPRISE)["usd"],
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
