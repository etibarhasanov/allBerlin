"""The runner, against a fake Nearby Search with a known ground truth.

The one thing a hex census must get right that a bounding-box sweep never has
to: a cell's count is the places inside that cell's circle, and nothing else.
With coordinates on every result that is a filter; these tests hold it to it.
"""

import math

import pytest

pytest.importorskip("h3")
pytest.importorskip("allrestaurants", reason="needs a checkout of allRestaurants")

from allrestaurants.geo import haversine_m

from berlin import hexgrid
from berlin.runner import (FIELD_MASK, CountStore, HexCensus, categorise)


class FakePlaces:
    """The nearest 20 of a fixed point set, with coordinates and types --
    what Nearby Search Pro returns for an untyped request."""

    def __init__(self, places):
        self.places = places        # (id, lat, lng, types)
        self.request_count = 0
        self.type_filters = []

    def search_nearby(self, circle, included_types=(), **kwargs):
        self.request_count += 1
        self.type_filters.append(tuple(included_types))
        inside = [
            (haversine_m(circle.lat, circle.lng, lat, lng), pid, lat, lng, types)
            for pid, lat, lng, types in self.places
            if haversine_m(circle.lat, circle.lng, lat, lng) <= circle.radius_m
        ]
        inside.sort()
        return [
            {"id": pid, "displayName": {"text": pid},
             "location": {"latitude": lat, "longitude": lng},
             "types": list(types), "primaryType": types[0] if types else None}
            for _, pid, lat, lng, types in inside[:20]
        ]


def clump(cell, n, types=("store",), spread_m=60.0, offset_m=0.0):
    """n places packed inside a cell's query circle."""
    lat, lng, _ = hexgrid.cell_query_circle(cell)
    out = []
    for i in range(n):
        angle = 2 * math.pi * i / n
        # A floor on the radius: coincident points can never be separated by
        # any split, which would test the fixture rather than the runner.
        radius = offset_m + spread_m * (0.2 + 0.8 * (i % 7) / 7.0)
        out.append((f"p{i}",
                    lat + radius * math.cos(angle) / 111_320.0,
                    lng + radius * math.sin(angle) / 67_700.0,
                    types if isinstance(types, tuple) else (types[i % len(types)],)))
    return out


@pytest.fixture
def store(tmp_path):
    s = CountStore(str(tmp_path / "census.db"))
    yield s
    s.close()


def _cell():
    return hexgrid.berlin_cells(9)[5000]


def test_the_field_mask_stays_on_the_pro_tier():
    """One rating in here re-prices every call to Enterprise."""
    for f in FIELD_MASK.split(","):
        assert not any(k in f for k in ("rating", "Rating", "price", "phone",
                                        "website", "OpeningHours", "reviews"))
    assert "places.location" in FIELD_MASK and "places.types" in FIELD_MASK


def test_a_quiet_cell_costs_one_call_and_asks_for_everything(store):
    cell = _cell()
    client = FakePlaces(clump(cell, 5))
    census = HexCensus(client, store, 9, workers=1)
    assert len(census.count_cell(cell)) == 5
    assert census.stats.calls == 1
    assert client.type_filters == [()]      # untyped: no includedTypes


@pytest.mark.parametrize("n", [25, 40, 90, 200])
def test_a_saturated_cell_is_quartered_to_the_exact_count(store, n):
    cell = _cell()
    client = FakePlaces(clump(cell, n))
    census = HexCensus(client, store, 9, workers=1)
    found = census.count_cell(cell)
    assert len(found) == n
    assert census.stats.splits > 0


def test_results_outside_the_cell_are_clipped(store):
    """Quartering reaches to 1.43r. Without coordinates that was a 21%
    over-count; with them it is a filter."""
    cell = _cell()
    lat, lng, r = hexgrid.cell_query_circle(cell)
    inside = clump(cell, 30)                         # forces a split
    outside = clump(cell, 12, offset_m=r * 1.15)     # inside a child, outside the cell
    client = FakePlaces(inside + [(f"o{i}", a, b, t) for i, (_, a, b, t) in enumerate(outside)])
    census = HexCensus(client, store, 9, workers=1)
    found = census.count_cell(cell)
    assert set(found) == {p[0] for p in inside}
    assert census.stats.clipped > 0


def test_every_stored_place_has_coordinates_and_a_category(store):
    cell = _cell()
    types = ["cafe", "store", "pharmacy", "hair_salon"]
    client = FakePlaces(clump(cell, 8, types=types))
    HexCensus(client, store, 9, workers=1).count_cell(cell)
    rows = store.iter_places()
    assert len(rows) == 8
    for pid, name, lat, lng, primary, tps, category, addr, status in rows:
        assert 52 < lat < 53 and 13 < lng < 14
        assert category in {"food_drink", "retail", "health", "services_personal"}


def test_counts_come_back_by_category(store):
    cell = _cell()
    client = FakePlaces(clump(cell, 6, types=["cafe", "cafe", "store"]))
    HexCensus(client, store, 9, workers=1).count_cell(cell)
    assert store.counts(9) == {cell: {"food_drink": 4, "retail": 2}}


def test_a_place_google_types_as_nothing_we_know_is_kept_as_other(store):
    cell = _cell()
    client = FakePlaces(clump(cell, 3, types=("park",)))
    HexCensus(client, store, 9, workers=1).count_cell(cell)
    assert store.counts(9) == {cell: {"other": 3}}


def test_categorise_prefers_the_primary_type():
    assert categorise(["store", "bakery"], primary="bakery") == "food_drink"
    assert categorise(["store", "bakery"], primary=None) == "retail"  # first known in list
    assert categorise(["park"]) is None


def test_ids_deduplicate_across_the_seam_between_cells(store):
    cell = _cell()
    neighbour = [c for c in hexgrid.ring(cell, 1) if c != cell][0]
    a = hexgrid.cell_center(cell)
    b = hexgrid.cell_center(neighbour)
    seam = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    shared = [(f"s{i}", seam[0] + (i % 3) * 0.00012, seam[1] + (i // 3) * 0.0002,
               ("store",)) for i in range(10)]
    client = FakePlaces(shared)
    HexCensus(client, store, 9, workers=1).count_cell(cell)
    HexCensus(client, store, 9, workers=1).count_cell(neighbour)
    per_cell = sum(sum(c.values()) for c in store.counts(9).values())
    assert per_cell > 10                       # naive addition inflates
    assert store.unique_places() == 10         # ids do not


def test_a_finished_cell_is_not_paid_for_twice(store):
    cell = _cell()
    client = FakePlaces(clump(cell, 8))
    HexCensus(client, store, 9, workers=1).run([cell])
    first = client.request_count
    again = HexCensus(client, store, 9, workers=1)
    again.run([cell])
    assert client.request_count == first
    assert again.stats.cells_skipped == 1


def test_one_bad_cell_does_not_lose_the_run(store):
    cells = hexgrid.berlin_cells(9)[5000:5003]

    class Flaky(FakePlaces):
        def search_nearby(self, circle, **kwargs):
            if abs(circle.lat - hexgrid.cell_center(cells[1])[0]) < 1e-9:
                raise RuntimeError("simulated failure")
            return super().search_nearby(circle, **kwargs)

    stats = HexCensus(Flaky([]), store, 9, workers=1).run(cells)
    assert stats.cells_failed == 1
    assert stats.cells_done == 2
