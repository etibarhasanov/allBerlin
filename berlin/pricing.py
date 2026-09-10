"""Google Maps Platform billing, as it works since 1 March 2025.

Two things changed that quarter and both matter here.

The pooled $200 monthly credit is gone.  Each SKU now carries its own free
monthly call count -- 10,000 for Essentials, 5,000 for Pro, 1,000 for
Enterprise -- and they neither pool nor roll over.  A sweep that would have
been free under the old credit is now billed from a much smaller allowance:
1,000 calls, not $200 worth.

A request is billed at the highest SKU any field in its mask belongs to.
Asking for one review count on a call that is otherwise Pro re-prices the whole
call as Enterprise.  There is no partial billing, so the field mask is the
single biggest lever on the bill after the number of calls itself.

Prices are US list, first volume band, checked September 2026.  Google moves
them; ``--price-per-call`` overrides every figure here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True)
class Sku:
    """One billable Google Places SKU."""

    name: str
    # Field tier in allRestaurants' --tier vocabulary, where one exists.
    tier: Optional[str]
    usd_per_1000: float
    free_calls_per_month: int
    buys: str

    @property
    def usd_per_call(self) -> float:
        return self.usd_per_1000 / 1000.0


# Nearby Search: one call returns up to 20 places.
NEARBY_IDS = Sku(
    "Nearby Search Essentials (IDs Only)", "ids", 0.00, 0,
    "place IDs and nothing else -- no name, no rating, no location",
)
NEARBY_PRO = Sku(
    "Nearby Search Pro", "standard", 32.00, 5_000,
    "name, address, location, types, business status",
)
NEARBY_ENTERPRISE = Sku(
    "Nearby Search Enterprise", "ratings", 35.00, 1_000,
    "the above plus rating, review count, price level, phone, website, hours",
)
NEARBY_ATMOSPHERE = Sku(
    "Nearby Search Enterprise + Atmosphere", "full", 40.00, 1_000,
    "the above plus review text, editorial summary and service attributes",
)

# Place Details: one call refreshes one place you already have the ID for.
DETAILS_IDS = Sku(
    "Place Details Essentials (IDs Only)", None, 0.00, 0,
    "confirms a place ID still resolves",
)
DETAILS_PRO = Sku(
    "Place Details Pro", None, 17.00, 5_000,
    "name, address, location, types for one place",
)
DETAILS_ENTERPRISE = Sku(
    "Place Details Enterprise", None, 20.00, 1_000,
    "the above plus rating, review count, phone, website, hours for one place",
)
DETAILS_ATMOSPHERE = Sku(
    "Place Details Enterprise + Atmosphere", None, 25.00, 1_000,
    "the above plus review text and service attributes for one place",
)

NEARBY_SKUS: List[Sku] = [NEARBY_IDS, NEARBY_PRO, NEARBY_ENTERPRISE, NEARBY_ATMOSPHERE]
DETAILS_SKUS: List[Sku] = [DETAILS_IDS, DETAILS_PRO, DETAILS_ENTERPRISE, DETAILS_ATMOSPHERE]

BY_TIER: Dict[str, Sku] = {s.tier: s for s in NEARBY_SKUS if s.tier}

# Google Cloud's trial for a new billing account: credits, and a clock.
FREE_TRIAL_USD = 300.0
FREE_TRIAL_DAYS = 90

# The IDs-Only SKUs are free with no monthly cap at all, which is a real lever
# and a trap in equal measure -- see cost.py, ids_only_is_a_false_economy().
UNLIMITED_FREE_SKUS = (NEARBY_IDS, DETAILS_IDS)


def bill(calls: int, sku: Sku, months: int = 1) -> Dict[str, float]:
    """Price ``calls`` of ``sku``, spread over ``months`` calendar months.

    Spreading matters because the free allowance is monthly and does not roll
    over: 1,000 free Enterprise calls in January are worth nothing in February
    unless you are still running in February.
    """
    if calls < 0:
        raise ValueError("calls cannot be negative")
    if months < 1:
        raise ValueError("months must be at least 1")
    free = min(calls, sku.free_calls_per_month * months)
    billable = calls - free
    return {
        "calls": float(calls),
        "free_calls": float(free),
        "billable_calls": float(billable),
        "usd": billable * sku.usd_per_call,
        "usd_before_free_tier": calls * sku.usd_per_call,
    }
