"""The runner, against a fake Nearby Search with a known ground truth.

The point of these is the one thing a hex census must get right and a
bounding-box sweep never has to: a cell's count has to be the places in that
cell's circle, and nothing else.
"""

import math

import pytest

h3 = pytest.importorskip("h3")
pytest.importorskip("allrestaurants", reason="needs a checkout of allRestaurants")

from allrestaurants.geo import haversine_m

from berlin import hexgrid
from berlin.entities import by_key
from berlin.runner import CountStore, HexCensus


class FakePlaces:
    """The nearest 20 places matching the requested types, as the API does."""

    def __init__(self, places):
        self.places = places        # (id, lat, lng, type)
        self.request_count = 0
        self.type_sets = []

    def search_nearby(self, circle, included_types=(), **kwargs):
        self.request_count += 1
        self.type_sets.append(tuple(included_types))
        wanted = set(included_types)
        inside = [
            (haversine_m(circle.lat, circle.lng, lat, lng), pid)
            for pid, lat, lng, kind in self.places
            if kind in wanted
            and haversine_m(circle.lat, circle.lng, lat, lng) <= circle.radius_m
        ]
        inside.sort()
        return [{"id": pid} for _, pid in inside[:20]]


def clump(cell, n, types, spread_m=60.0):
    """n places packed well inside a cell's query circle."""
    lat, lng, _ = hexgrid.cell_query_circle(cell)
    out = []
    for i in range(n):
        angle = 2 * math.pi * i / n
        radius = spread_m * ((i % 7) / 7.0)
        out.append((f"p{i}",
                    lat + radius * math.cos(angle) / 111_320.0,
                    lng + radius * math.sin(angle) / 67_700.0,
                    types[i % len(types)]))
    return out


@pytest.fixture
def store(tmp_path):
    s = CountStore(str(tmp_path / "census.db"))
    yield s
    s.close()


def _cell():
    return hexgrid.berlin_cells(9)[5000]


def test_a_quiet_cell_costs_one_call(store):
    cell = _cell()
    category = by_key("retail")
    client = FakePlaces(clump(cell, 5, category.types))
    census = HexCensus(client, store, category, 9, workers=1)
    assert len(census.count_cell(cell)) == 5
    assert census.stats.calls == 1
    assert census.stats.splits == 0


@pytest.mark.parametrize("n", [25, 40, 90, 200])
def test_type_splitting_returns_the_exact_count(store, n):
    """The whole reason saturation is broken on the type list rather than on
    the circle: every result stays inside the cell being measured."""
    cell = _cell()
    category = by_key("retail")
    places = clump(cell, n, category.types)
    client = FakePlaces(places)
    census = HexCensus(client, store, category, 9, workers=1)
    found = census.count_cell(cell)
    assert len(found) == n
    assert census.stats.calls > 1
    assert census.stats.inexact_cells == 0


def test_type_splitting_queries_the_same_circle_throughout(store):
    """If it ever moved the circle, results from outside the cell would be
    attributed to it -- a 21% over-count, measured, and uncorrectable because
    an IDs-Only response carries no coordinates to filter on."""
    cell = _cell()
    category = by_key("retail")
    client = FakePlaces(clump(cell, 90, category.types))
    HexCensus(client, store, category, 9, workers=1).count_cell(cell)
    assert len(client.type_sets) > 1
    assert all(set(ts) <= set(category.types) for ts in client.type_sets)
    # The full list first, then strict subsets of it.
    assert client.type_sets[0] == tuple(category.types)
    assert all(len(ts) < len(category.types) for ts in client.type_sets[1:])


def test_a_single_saturating_type_falls_back_to_the_grid_and_says_so(store):
    cell = _cell()
    category = by_key("retail")
    client = FakePlaces(clump(cell, 40, ["store"]))
    census = HexCensus(client, store, category, 9, workers=1)
    census.count_cell(cell)
    assert census.stats.inexact_cells == 1


def test_counts_and_ids_are_both_stored(store):
    cell = _cell()
    category = by_key("retail")
    client = FakePlaces(clump(cell, 12, category.types))
    HexCensus(client, store, category, 9, workers=1).count_cell(cell)
    assert store.counts(9) == {cell: {"retail": 12}}
    assert store.unique_entities() == 12
    assert store.unique_entities("retail") == 12
    assert store.unique_entities("lodging") == 0


def test_ids_deduplicate_across_overlapping_cells(store):
    """Neighbouring query circles overlap by about a fifth, so adding cell
    counts would double-count. Ids make the city total exact."""
    cell = _cell()
    neighbour = [c for c in hexgrid.ring(cell, 1) if c != cell][0]
    category = by_key("retail")
    # On the seam between the two cells, so both circles reach it.
    a = hexgrid.cell_center(cell)
    b = hexgrid.cell_center(neighbour)
    seam = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    shared = [(f"s{i}", seam[0] + (i % 3) * 0.00012,
               seam[1] + (i // 3) * 0.0002, category.types[i % 5])
              for i in range(10)]
    client = FakePlaces(shared)
    HexCensus(client, store, category, 9, workers=1).count_cell(cell)
    HexCensus(client, store, category, 9, workers=1).count_cell(neighbour)
    counts = store.counts(9)
    assert sum(c["retail"] for c in counts.values()) > 10   # naive sum inflates
    assert store.unique_entities() == 10                    # ids do not


def test_a_finished_cell_is_not_paid_for_twice(store):
    cell = _cell()
    category = by_key("retail")
    client = FakePlaces(clump(cell, 8, category.types))
    census = HexCensus(client, store, category, 9, workers=1)
    census.run([cell])
    first = client.request_count
    again = HexCensus(client, store, category, 9, workers=1)
    again.run([cell])
    assert client.request_count == first
    assert again.stats.cells_skipped == 1


def test_one_bad_cell_does_not_lose_the_run(store):
    cells = hexgrid.berlin_cells(9)[5000:5003]
    category = by_key("lodging")

    class Flaky(FakePlaces):
        def search_nearby(self, circle, **kwargs):
            if abs(circle.lat - hexgrid.cell_center(cells[1])[0]) < 1e-9:
                raise RuntimeError("simulated failure")
            return super().search_nearby(circle, **kwargs)

    census = HexCensus(Flaky([]), store, category, 9, workers=1)
    stats = census.run(cells)
    assert stats.cells_failed == 1
    assert stats.cells_done == 2


def test_the_census_never_asks_for_a_review_count(store):
    """It cannot: the free SKU does not carry one. If this ever changes the
    sweep stops being free, so it is worth a test rather than a comment."""
    cell = _cell()
    category = by_key("food_drink")
    client = FakePlaces(clump(cell, 5, category.types))
    census = HexCensus(client, store, category, 9, workers=1)
    census.count_cell(cell)
    assert not hasattr(census, "min_reviews")
