"""The census plan: how many calls, how many hours, and what it costs."""

import pytest

from berlin.census import (BERLIN_PRIVATE_ENTITIES, CALLS_PER_EXCESS_MULTIPLE,
                           DEFAULT_SCORING_RESOLUTION, cell_densities,
                           centre_gradient, cost_pass, enrichment_cost,
                           entities_in, modelled_counts, modelled_population,
                           plan_census, settled_density, total_entities)
from berlin.districts import DISTRICTS, by_name
from berlin.entities import by_key
from berlin.hexgrid import resolution
from berlin.pricing import NEARBY_IDS, NEARBY_PRO


def test_the_census_is_free():
    """The whole economic argument. IDs-Only has no monthly cap."""
    plan = plan_census()
    assert plan.sku is NEARBY_IDS
    assert plan.billing()["usd"] == 0.0
    assert plan.calls > 100_000


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


def test_finer_resolutions_cost_more_calls_and_saturate_less():
    coarse = plan_census(res=8)
    fine = plan_census(res=10)
    assert fine.calls > coarse.calls
    assert fine.saturated_cells < coarse.saturated_cells


def test_resolution_is_a_product_choice_not_a_cost_optimisation():
    """Minimising calls alone would pick the coarsest grid every time, because
    splitting is cheaper than laying seven cells. The default is not that."""
    cheapest = min((8, 9, 10), key=lambda r: plan_census(res=r).calls)
    assert cheapest == 8
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
    """Measured against the type splitter in runner.py, not assumed."""
    assert CALLS_PER_EXCESS_MULTIPLE == pytest.approx(3.75)


def test_hours_follow_calls():
    plan = plan_census()
    assert plan.hours == pytest.approx(plan.calls / 10.0 / 3600.0)
    assert 1 < plan.hours < 12


def test_enrichment_is_where_the_money_would_be():
    plan = plan_census()
    e = enrichment_cost(plan.entities, plan.calls)
    assert e["sweep_at_pro_usd"] > 1000
    assert plan.billing()["usd"] == 0


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
