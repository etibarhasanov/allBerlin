"""The hex grid, and the circle each cell is queried as."""

import math

import pytest

from berlin import hexgrid
from berlin.geometry import BERLIN_OUTLINE, contains
from berlin.hexgrid import (MAX_RESULTS_PER_CALL, berlin_cells, cell_center,
                            cell_query_circle, children, recommended_resolution,
                            resolution, ring, ring_size)


def test_the_query_circle_circumscribes_its_cell():
    """A hexagon's circumradius is its edge, so the circle must cover the
    cell -- a smaller one would leave the six corners unsearched."""
    for res in (8, 9, 10):
        r = resolution(res)
        assert r.query_radius_m >= r.edge_m
        assert r.query_area_km2 > r.cell_area_km2


def test_the_overlap_is_about_a_fifth():
    """pi*e^2 / (3*sqrt(3)/2 * e^2) = 1.209, before the safety margin."""
    for res in (8, 9, 10):
        r = resolution(res)
        assert 1.20 < r.query_area_km2 / r.cell_area_km2 < 1.30


def test_finer_cells_tolerate_more_density():
    densities = [resolution(r).saturating_density for r in (8, 9, 10)]
    assert densities == sorted(densities)


def test_saturating_density_is_the_cap_over_the_query_area():
    r = resolution(9)
    assert r.saturating_density * r.query_area_km2 == pytest.approx(
        MAX_RESULTS_PER_CALL)


def test_berlin_cells_scale_by_seven():
    """H3's aperture: each resolution is seven times the last."""
    counts = {r: len(berlin_cells(r)) for r in (8, 9)}
    assert counts[9] / counts[8] == pytest.approx(7, rel=0.05)


def test_every_cell_centre_is_in_berlin():
    for cell in berlin_cells(8):
        assert contains(BERLIN_OUTLINE, *cell_center(cell))


def test_the_grid_covers_about_the_city():
    cells = berlin_cells(9)
    covered = len(cells) * resolution(9).cell_area_km2
    assert 900 < covered < 1300


def test_ring_sizes_follow_the_hex_formula():
    assert [ring_size(k) for k in range(4)] == [1, 7, 19, 37]
    cell = berlin_cells(9)[0]
    for k in (0, 1, 2):
        assert len(ring(cell, k)) == ring_size(k)


def test_a_cell_is_in_its_own_ring():
    cell = berlin_cells(9)[100]
    assert cell in ring(cell, 1)


def test_children_are_seven_and_one_step_finer():
    cell = berlin_cells(9)[100]
    kids = children(cell)
    assert len(kids) == 7
    assert all(len(k) == len(cell) for k in kids)


def test_recommended_resolution_gets_finer_as_density_rises():
    resolutions = [recommended_resolution(d) for d in (5, 50, 500, 5000)]
    assert resolutions == sorted(resolutions)


def test_recommended_resolution_stays_under_the_cap():
    for density in (10, 100, 1000):
        res = recommended_resolution(density)
        assert density * resolution(res).query_area_km2 <= MAX_RESULTS_PER_CALL


def test_a_bad_resolution_is_refused():
    with pytest.raises(ValueError):
        resolution(20)
