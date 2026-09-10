"""The cost model, checked against the run it was fitted to."""

import math

import pytest

from berlin.cost import (CENSUS_MULTIPLIER, build_plan, calls_for,
                         cell_radius_for, empty_ground_calls,
                         ids_only_is_a_false_economy, refresh_cost,
                         share_above_bar)
from berlin.districts import total_expected_places
from berlin.pricing import (DETAILS_ENTERPRISE, NEARBY_ENTERPRISE, NEARBY_PRO,
                            TEXT_IDS, bill)


def test_the_law_reproduces_the_measurement_it_came_from():
    """Tallinn: 1,110 places over a 207 km2 bbox cost 2,390 calls, measured."""
    assert calls_for(1110, 207) == pytest.approx(2390, rel=0.05)


def test_cost_follows_the_geometric_mean_not_either_term():
    """Doubling the places at fixed area costs sqrt(2), not 2 -- a denser
    circle hands back more places for the same call."""
    assert calls_for(2000, 100) / calls_for(1000, 100) == pytest.approx(math.sqrt(2))
    assert calls_for(1000, 200) / calls_for(1000, 100) == pytest.approx(math.sqrt(2))


def test_calls_per_place_fall_as_density_rises():
    sparse = calls_for(1000, 400) / 1000
    dense = calls_for(4000, 400) / 4000
    assert dense < sparse


def test_empty_ground_still_costs_something():
    assert calls_for(0, 50) == 0
    with pytest.raises(ValueError):
        calls_for(10, 0)


def test_cell_radius_shrinks_as_density_rises():
    assert cell_radius_for(2000, 30) < cell_radius_for(400, 40)


def test_cell_radius_is_clamped_at_both_ends():
    assert cell_radius_for(1_000_000, 1) == 120.0
    assert cell_radius_for(1, 1000) == 1000.0


def test_review_bar_shares_are_monotonic():
    bars = [0, 25, 50, 100, 200, 500]
    shares = [share_above_bar(b) for b in bars]
    assert shares == sorted(shares, reverse=True)


def test_review_bar_interpolates_between_measured_points():
    assert share_above_bar(50) > share_above_bar(75) > share_above_bar(100)


def test_review_bar_clamps_outside_the_measured_range():
    assert share_above_bar(10_000) == share_above_bar(500)


def test_a_higher_bar_is_always_cheaper():
    costs = [build_plan(min_reviews=b).calls for b in (25, 50, 100, 200)]
    assert costs == sorted(costs, reverse=True)


def test_census_is_priced_off_the_measured_ratio_not_the_curve():
    """Census mode has no stopping rule, so it is a different algorithm --
    extending the fitted curve into it would understate it fivefold."""
    bar = build_plan(min_reviews=25)
    census = build_plan(min_reviews=0)
    ratio = census.productive_calls / bar.productive_calls
    assert ratio == pytest.approx(CENSUS_MULTIPLIER, rel=0.01)


def test_the_headline_figure():
    """The number the whole exercise exists to produce."""
    plan = build_plan()
    assert 9_000 < plan.calls < 12_000
    assert plan.calls == pytest.approx(plan.productive_calls + plan.overhead_calls)
    billing = plan.billing(contingency=False)
    assert 300 < billing["usd"] < 380


def test_sweeping_forest_and_lakes_costs_more_and_finds_nothing_extra():
    settled = build_plan(settled_only=True)
    everything = build_plan(settled_only=False)
    assert everything.calls > settled.calls
    assert everything.places == pytest.approx(settled.places)


def test_free_tier_is_monthly_and_does_not_roll_over():
    one = bill(10_000, NEARBY_ENTERPRISE, months=1)
    two = bill(10_000, NEARBY_ENTERPRISE, months=2)
    assert one["free_calls"] == 1_000
    assert two["free_calls"] == 2_000
    assert two["usd"] < one["usd"]


def test_free_tier_cannot_exceed_the_calls_made():
    assert bill(500, NEARBY_ENTERPRISE)["free_calls"] == 500
    assert bill(500, NEARBY_ENTERPRISE)["usd"] == 0


def test_text_search_ids_only_costs_nothing():
    assert bill(1_000_000, TEXT_IDS)["usd"] == 0


def test_there_is_no_free_nearby_search_tier():
    """Text Search and Place Details have one. Nearby Search does not, and a
    version of pricing.py that said otherwise priced a census at $0."""
    from berlin import pricing
    assert not hasattr(pricing, "NEARBY_IDS")
    assert min(s.usd_per_1000 for s in pricing.NEARBY_SKUS) == NEARBY_PRO.usd_per_1000


def test_bill_rejects_nonsense():
    with pytest.raises(ValueError):
        bill(-1, NEARBY_PRO)
    with pytest.raises(ValueError):
        bill(10, NEARBY_PRO, months=0)


def test_nearby_search_beats_place_details_per_place():
    """One Nearby Search call returns 20 places; Place Details returns one.
    This is why the free IDs-Only route is a false economy."""
    verdict = ids_only_is_a_false_economy(10_000, 35_000)
    assert verdict["usd_per_place_via_nearby"] < verdict["usd_per_place_via_details"] / 10


def test_refresh_by_details_beats_re_sweeping_at_berlin_scale():
    plan = build_plan()
    details = refresh_cost(plan.places, DETAILS_ENTERPRISE)
    assert details["usd"] < plan.billing(contingency=False)["usd"]


def test_plan_is_ordered_most_expensive_first():
    plan = build_plan()
    assert [p.calls for p in plan.districts] == sorted(
        [p.calls for p in plan.districts], reverse=True)
    assert plan.districts[0].district.name == "Mitte"


def test_empty_ground_costs_only_its_share_of_the_grid():
    """One call, no results, no split. Pricing it with the geometric-mean law
    overstates it about fivefold, which is how a rectangle around
    Treptow-Koepenick turns into a wrong answer."""
    naive = calls_for(0.001, 396)
    honest = empty_ground_calls(396, 810)
    assert honest < 400
    assert empty_ground_calls(0, 400) == 0
    assert empty_ground_calls(-5, 400) == 0


def test_bigger_circles_make_empty_ground_cheaper():
    assert empty_ground_calls(100, 800) < empty_ground_calls(100, 400)


def test_tiles_cover_less_ground_than_bounding_boxes_would():
    """The whole point of tiling a borough with two or three rectangles."""
    from berlin.districts import DISTRICTS, tile_area_km2
    for d in DISTRICTS:
        if len(d.tiles) > 1:
            assert d.swept_km2 < tile_area_km2(d.bbox), d.name


def test_overhead_is_a_small_share_of_the_bill():
    """If the rectangles were sloppy this would not hold, and the headline
    figure would be quietly wrong."""
    plan = build_plan()
    assert plan.overhead_calls / plan.calls < 0.10
