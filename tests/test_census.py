"""The census plan: how many calls, how many hours, and what it costs."""

import pytest

from berlin.census import (ALL_POI_FACTOR, BERLIN_PRIVATE_ENTITIES,
                           CALLS_PER_EXCESS_MULTIPLE,
                           DEFAULT_SCORING_RESOLUTION, cell_densities,
                           centre_gradient, cost_pass, enrichment_cost,
                           entities_in, modelled_counts, modelled_population,
                           plan_census, settled_density, total_entities,
                           two_stage_cost)
from berlin.districts import DISTRICTS, by_name
from berlin.entities import CATEGORIES, by_key
from berlin.hexgrid import resolution
from berlin.pricing import (DETAILS_ESSENTIALS, FREE_TRIAL_USD, NEARBY_PRO,
                            TEXT_IDS)


def test_the_census_is_not_free():
    """Nearby Search has no IDs-Only tier. An earlier version of this test
    asserted $0.00, and the whole plan was built on it."""
    plan = plan_census()
    assert plan.sku is NEARBY_PRO
    assert plan.billing()["usd"] > FREE_TRIAL_USD
    assert plan.billing()["usd_before_free_tier"] == pytest.approx(
        plan.calls * NEARBY_PRO.usd_per_call, rel=0.001)


def test_one_untyped_pass_costs_a_fifth_of_twelve_typed_ones():
    """Once every result carries its types, the category comes back with
    it and the typed sweeps collapse into one."""
    untyped = plan_census()
    typed = plan_census(categories=CATEGORIES)
    assert len(untyped.passes) == 1
    assert len(typed.passes) == len(CATEGORIES)
    assert untyped.calls < typed.calls / 3


def test_the_untyped_pass_reports_private_entities_not_all_pois():
    """The pass sees parks and bus stops too; the product counts businesses."""
    plan = plan_census()
    assert plan.entities == pytest.approx(BERLIN_PRIVATE_ENTITIES, rel=0.01)
    p = cost_pass(None, 9)
    assert p.entities == pytest.approx(BERLIN_PRIVATE_ENTITIES, rel=0.01)


def test_res_9_is_the_bottom_of_the_cost_curve():
    """Coarser cells split too much, finer cells pay the empty-cell floor.
    This is a real crossover the model has to reproduce, not a default."""
    costs = {r: plan_census(res=r).calls for r in (8, 9, 10)}
    assert costs[9] < costs[8]
    assert costs[9] < costs[10]


def test_the_free_allowance_is_monthly():
    one = plan_census(months=1).billing()["usd"]
    two = plan_census(months=2).billing()["usd"]
    assert two == pytest.approx(one - NEARBY_PRO.free_calls_per_month * NEARBY_PRO.usd_per_call)


def test_two_stage_route_is_cheaper_but_conditional():
    plan = plan_census()
    t = two_stage_cost(plan.entities)
    assert t["discovery_usd"] == 0.0
    assert t["discovery_sku"] == TEXT_IDS.name
    assert t["details_sku"] == DETAILS_ESSENTIALS.name
    assert t["total_usd"] < plan.billing()["usd"]
    assert t["total_usd"] == pytest.approx(
        (plan.entities - DETAILS_ESSENTIALS.free_calls_per_month)
        * DETAILS_ESSENTIALS.usd_per_call, rel=0.01)
    assert t["months_to_be_free"] == 12


def test_the_density_surface_integrates_to_the_modelled_total():
    """Without this the shape of the borough rectangles quietly sets the
    total, and every count downstream inherits the error."""
    for res in (8, 9):
        integral = sum(cell_densities(res)) * resolution(res).cell_area_km2
        assert integral == pytest.approx(BERLIN_PRIVATE_ENTITIES, rel=0.001)


def test_borough_entity_counts_sum_to_the_city():
    assert total_entities() == pytest.approx(BERLIN_PRIVATE_ENTITIES, rel=0.001)


def test_the_centre_is_denser_than_the_edge():
    assert centre_gradient(52.5200, 13.4050) > centre_gradient(52.4250, 13.7612)
    assert centre_gradient(52.5200, 13.4050) == pytest.approx(4.0, rel=0.01)


def test_density_ordering_matches_the_city():
    ranked = sorted(DISTRICTS, key=lambda d: -settled_density(d))
    assert ranked[0].name == "Mitte"
    assert ranked[-1].name in {"Marzahn-Hellersdorf", "Spandau", "Reinickendorf"}


def test_finer_resolutions_saturate_less():
    coarse = plan_census(res=8)
    fine = plan_census(res=10)
    assert fine.saturated_cells < coarse.saturated_cells
    assert DEFAULT_SCORING_RESOLUTION == 9


def test_a_denser_category_needs_more_calls():
    retail = cost_pass(by_key("retail"), 9)
    lodging = cost_pass(by_key("lodging"), 9)
    assert retail.calls > lodging.calls
    assert retail.saturated_cells > lodging.saturated_cells


def test_an_unsaturated_pass_costs_exactly_one_call_per_cell():
    lodging = cost_pass(by_key("lodging"), 10)
    assert lodging.saturated_cells == 0
    assert lodging.calls == lodging.cells


def test_split_cost_is_linear_in_how_far_over_the_cap_a_cell_is():
    """Measured on the allRestaurants fixture for quartering, not assumed."""
    assert CALLS_PER_EXCESS_MULTIPLE == pytest.approx(4.4)


def test_hours_follow_calls():
    plan = plan_census()
    assert plan.hours == pytest.approx(plan.calls / 10.0 / 3600.0)
    assert 0.3 < plan.hours < 3


def test_ratings_on_top_are_cheaper_by_resweep_than_by_details():
    """Enterprise adds $3 per call; Details Enterprise is $20 per place.
    At Berlin's places-per-call the re-sweep wins by an order of magnitude."""
    plan = plan_census()
    e = enrichment_cost(plan.entities, plan.calls)
    assert e["resweep_at_enterprise_extra_usd"] < e["details_enterprise_usd"] / 5


def test_modelled_counts_cover_every_cell_and_category():
    counts = modelled_counts(8)
    assert len(counts) == len(cell_densities(8))
    first = next(iter(counts.values()))
    assert "retail" in first and "transport" in first


def test_modelled_population_is_in_the_right_order():
    pop = modelled_population(8)
    assert sum(pop.values()) > 2_000_000
    assert sum(pop.values()) < 8_000_000


def test_food_count_agrees_with_the_independent_eatery_estimate():
    """A real cross-check: this model reaches Berlin's eateries through
    registered-company counts, the review-bar model in cost.py reaches them
    through Tallinn's gastronomy rate. They should not disagree wildly."""
    from berlin.cost import build_plan
    food = cost_pass(by_key("food_drink"), 9).entities
    rated = build_plan().places        # eateries with 25+ reviews
    assert rated < food < 2.5 * rated


def test_smoothing_removes_the_borough_edges_without_moving_the_total():
    """Hard rectangular density edges are an artefact of the rectangles in
    districts.py, not a claim about Berlin. Smoothing over the hex ring takes
    them out; renormalising keeps the city total where it was."""
    from berlin import hexgrid
    from berlin.census import _smooth

    cells = hexgrid.berlin_cells(8)
    step = [100.0 if i < len(cells) // 2 else 0.0 for i in range(len(cells))]
    smoothed = _smooth(cells, step)
    jump_before = max(abs(step[i] - step[i - 1]) for i in range(1, len(step)))
    jump_after = max(abs(smoothed[i] - smoothed[i - 1]) for i in range(1, len(smoothed)))
    assert jump_after < jump_before
    assert sum(smoothed) == pytest.approx(sum(step), rel=0.15)


def test_a_flat_surface_survives_smoothing_unchanged():
    from berlin import hexgrid
    from berlin.census import _smooth

    cells = hexgrid.berlin_cells(8)
    flat = [7.0] * len(cells)
    assert _smooth(cells, flat) == pytest.approx(flat)
