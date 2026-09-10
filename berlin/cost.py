"""How many calls a sweep takes, and what that costs.

The estimate in allRestaurants assumes a fixed multiple of the starting grid --
"every dense circle splits into four" -- and that assumption has already been
wrong once by a factor of 1.7 on Tallinn's districts, in the expensive
direction.  It cannot be right in general, because splitting is driven by how
restaurants clump, and clumping is not something a grid knows about.

So this module does not assume.  ``tools/calibrate.py`` replays the real sweep
over the 1,110 real Tallinn coordinates, thickened two-, four- and eightfold to
stand in for a denser city, and measures what it costs.  Across an eightfold
density range the answer collapses to one line:

    calls  ~=  5.0 * sqrt(places * area_km2)

The geometric mean is the whole point.  Cost does not follow area -- an empty
square kilometre costs one call.  It does not follow the place count either --
a denser city returns more places per call, and calls per place *fall* as
density rises, from 2.15 in Tallinn to 0.77 at eight times its density.  Cost
follows the two together, and the constant held to within 7% at every density
measured.

Sanity check against the run that produced it: Tallinn, 1,110 places over a
207 km2 bbox, predicts 5.0 * sqrt(1110 * 207) = 2,397 calls.  Measured: 2,390.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional

from .districts import DISTRICTS, District
from .pricing import NEARBY_ENTERPRISE, Sku, bill

# Fitted in tools/calibrate.py over densities from 5.4 to 42.9 places/km2.
# Per-density constants were 4.99, 5.35, 4.86, 4.95.
CALLS_CONSTANT = 5.0

# The law is fitted in review-bar mode, where a circle stops splitting the
# moment it returns something below the bar.  Census mode has no such brake:
# every full circle splits until nothing saturates.  That is a different
# algorithm, not a denser version of the same one, so census is priced by the
# ratio actually measured between the two on the allRestaurants fixture --
# 2,176 calls against 358 -- rather than by extending a curve that does not
# reach there.
CENSUS_MULTIPLIER = 2176 / 358

# What the constant cannot see: a district whose clumping is unlike Tallinn's,
# a type filter that saturates circles sooner than the calibration did, circles
# that straddle the border and cover ground twice.  Every one of those pushes
# the same way, so the planning figure carries a margin and the measured figure
# is quoted beside it rather than instead of it.
CONTINGENCY = 0.25


def calls_for(places: float, area_km2: float, constant: float = CALLS_CONSTANT) -> float:
    """Calls to sweep ``area_km2`` holding ``places`` qualifying eateries."""
    if places < 0 or area_km2 <= 0:
        raise ValueError("places must be >= 0 and area_km2 > 0")
    return constant * math.sqrt(places * area_km2)


def cell_radius_for(places: float, area_km2: float) -> float:
    """The starting circle radius to run with, in metres.

    Sized so a circle holds about 20 places at the district's *average*
    density, which is the point where the API's 20-result cap starts binding.
    Splitting handles the clumps above average; a radius any larger just pays
    for parent calls whose ground the children re-cover, which the Tallinn
    measurements showed is the most expensive mistake available.
    """
    if places <= 0:
        return 1000.0
    density = places / area_km2
    radius_km = math.sqrt(20.0 / (math.pi * density))
    # Below 120m the splitter cannot resolve further anyway; above 1km a single
    # call spans more ground than Nearby Search ranks usefully.
    return max(120.0, min(1000.0, round(radius_km * 1000, -1)))


# Grid spacing is cell_radius * sqrt(2) * 0.98, from allrestaurants.geo, so one
# circle stands in for this many square metres of ground.
GROUND_PER_CIRCLE = 2.0 * 0.98 ** 2


def empty_ground_calls(extra_km2: float, cell_radius_m: float) -> float:
    """What over-covering costs, which is far less than it looks.

    A rectangle drawn around a borough always takes in ground the borough does
    not use -- a lake, a forest, the next borough's fields.  It is tempting to
    price that with the same law as the rest, but that law assumes circle size
    is tuned to density, and empty ground has none.  What actually happens is
    one call, no results, no split: an empty square kilometre costs exactly its
    share of the level-0 grid and nothing more.

    Treptow-Koepenick makes the difference concrete.  Its bounding box takes in
    396 km2 the sweep does not need.  Priced by the geometric-mean law that
    would be 1,545 calls; priced properly, at the 810 m circles that borough
    warrants, it is 314.
    """
    if extra_km2 <= 0:
        return 0.0
    spacing_km2 = GROUND_PER_CIRCLE * (cell_radius_m / 1000.0) ** 2
    return extra_km2 / spacing_km2


@dataclass
class DistrictPlan:
    district: District
    area_km2: float
    places: float
    calls: float
    cell_radius_m: float
    swept_km2: float = 0.0
    overhead_calls: float = 0.0

    @property
    def total_calls(self) -> float:
        return self.calls + self.overhead_calls

    @property
    def planning_calls(self) -> float:
        return self.total_calls * (1 + CONTINGENCY)

    @property
    def calls_per_place(self) -> float:
        return self.total_calls / self.places if self.places else float("nan")


@dataclass
class Plan:
    """A costed sweep of every borough."""

    districts: List[DistrictPlan]
    sku: Sku
    months: int
    min_reviews: int
    settled_only: bool

    @property
    def calls(self) -> float:
        return sum(p.total_calls for p in self.districts)

    @property
    def productive_calls(self) -> float:
        """Calls spent on ground that actually holds restaurants."""
        return sum(p.calls for p in self.districts)

    @property
    def overhead_calls(self) -> float:
        """Calls spent covering lakes, forest and the gaps between tiles."""
        return sum(p.overhead_calls for p in self.districts)

    @property
    def planning_calls(self) -> float:
        return sum(p.planning_calls for p in self.districts)

    @property
    def places(self) -> float:
        return sum(p.places for p in self.districts)

    @property
    def area_km2(self) -> float:
        return sum(p.area_km2 for p in self.districts)

    @property
    def swept_km2(self) -> float:
        return sum(p.swept_km2 for p in self.districts)

    def billing(self, contingency: bool = True) -> Dict[str, float]:
        calls = self.planning_calls if contingency else self.calls
        return bill(int(round(calls)), self.sku, self.months)


# Raising the review bar removes places, and it removes the numerous ones.
# Measured on the 1,110 Tallinn places: 892 also clear 50 reviews, 733 clear
# 100, 550 clear 200.  A bar is a cost lever twice over -- fewer places to
# find, and circles that reach their tail sooner.  The 0 entry is the census
# multiplier from the allRestaurants test fixture, where 400 eateries in a
# 1 km circle included 115 with 25+ reviews.
REVIEW_BAR_SHARE = {0: 3.48, 25: 1.000, 50: 0.892, 100: 0.733, 200: 0.550, 500: 0.308}


def share_above_bar(min_reviews: int) -> float:
    """Fraction of the 25+ review population that also clears ``min_reviews``."""
    if min_reviews in REVIEW_BAR_SHARE:
        return REVIEW_BAR_SHARE[min_reviews]
    known = sorted(k for k in REVIEW_BAR_SHARE if k > 0)
    if min_reviews < known[0]:
        return REVIEW_BAR_SHARE[0]
    if min_reviews > known[-1]:
        return REVIEW_BAR_SHARE[known[-1]]
    for lo, hi in zip(known, known[1:]):
        if lo <= min_reviews <= hi:
            t = (min_reviews - lo) / (hi - lo)
            return REVIEW_BAR_SHARE[lo] + t * (REVIEW_BAR_SHARE[hi] - REVIEW_BAR_SHARE[lo])
    raise AssertionError("unreachable")


def build_plan(
    sku: Sku = NEARBY_ENTERPRISE,
    min_reviews: int = 25,
    settled_only: bool = True,
    months: int = 1,
    districts: Optional[List[District]] = None,
) -> Plan:
    """Cost a full-city sweep under one set of choices."""
    share = share_above_bar(min_reviews)
    census = min_reviews <= 0
    plans = []
    for d in districts or DISTRICTS:
        area = d.settled_km2 if settled_only else d.area_km2
        places = d.expected_places * share
        if census:
            # Priced off the review-bar sweep of the same ground, scaled.
            calls = calls_for(d.expected_places, area) * CENSUS_MULTIPLIER
            radius = cell_radius_for(d.expected_places, area)
        else:
            calls = calls_for(places, area)
            radius = cell_radius_for(places, area)
        swept = d.swept_km2 if settled_only else max(d.swept_km2, d.area_km2)
        plans.append(
            DistrictPlan(
                district=d,
                area_km2=area,
                places=places,
                calls=calls,
                cell_radius_m=radius,
                swept_km2=swept,
                overhead_calls=empty_ground_calls(swept - area, radius),
            )
        )
    plans.sort(key=lambda p: -p.total_calls)
    return Plan(plans, sku, months, min_reviews, settled_only)


def refresh_cost(places: float, sku: Sku) -> Dict[str, float]:
    """What keeping the data current costs, once you already hold the IDs.

    Google lets place IDs be cached indefinitely and the content on them for
    about 30 days, so a live dataset needs re-collecting monthly.  Re-sweeping
    pays the discovery cost again; Place Details pays per place instead, which
    is worse per place and better in total only once the sweep is expensive
    enough -- the crossover is what this returns.
    """
    return bill(int(round(places)), sku, months=1)


def ids_only_is_a_false_economy(places: float, total_eateries: float) -> Dict[str, float]:
    """Why the free IDs-Only SKU does not make this free.

    Nearby Search Essentials (IDs Only) costs nothing, without limit, which
    invites an obvious plan: discover every place for free, then buy details
    only for what you want.  It does not work, for two compounding reasons.

    An IDs-only response carries no review count, so the stopping rule has
    nothing to read.  The sweep has to run as a census -- split every full
    circle until nothing saturates -- which on the Tallinn fixture cost 2,176
    calls against 358, six times more.  Free calls, so far so good.

    But a census finds *everything*, and most of everything is the long tail
    below the review bar.  You then hold ~3.5x as many IDs as you wanted, with
    no way to tell which are which until you buy details at $20 per 1,000 --
    eleven times the $1.75 per place that Nearby Search Enterprise charges when
    it returns 20 places for one $0.035 call.
    """
    from .pricing import DETAILS_ENTERPRISE

    census_details = bill(int(round(total_eateries)), DETAILS_ENTERPRISE)
    return {
        "ids_only_discovery_usd": 0.0,
        "places_discovered": total_eateries,
        "details_usd": census_details["usd"],
        "usd_per_place_via_details": DETAILS_ENTERPRISE.usd_per_call,
        "usd_per_place_via_nearby": NEARBY_ENTERPRISE.usd_per_call / 20.0,
    }
