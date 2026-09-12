"""Areas: a named circle, its cells, its cost, and its measured density."""

import pytest

from berlin import hexgrid
from berlin.areas import Area, cells_in, plan_area, plan_areas
from berlin.cli import main

ALEX = "Alexanderplatz:52.5219,13.4132:2"
SPANDAU = "Spandau:52.5370,13.2000:2"


def test_parse_and_reject():
    a = Area.parse(ALEX)
    assert a.name == "Alexanderplatz" and a.radius_km == 2
    with pytest.raises(ValueError):
        Area.parse("Potsdam:52.39,13.06:2")          # not Berlin
    with pytest.raises(ValueError):
        Area.parse("x:52.5,13.4:40")                  # absurd radius
    with pytest.raises(ValueError):
        Area.parse("just-a-name")


def test_a_2km_circle_holds_about_120_res9_cells():
    cells = cells_in(Area.parse(ALEX))
    assert 110 < len(cells) < 150
    for c in cells:
        lat, lng = hexgrid.cell_center(c)
        assert abs(lat - 52.5219) < 0.02 and abs(lng - 13.4132) < 0.032


def test_the_centre_costs_far_more_than_the_edge_for_the_same_cells():
    """Cost follows density, not area: same circle, thirty times the bill."""
    alex, spandau = plan_area(Area.parse(ALEX)), plan_area(Area.parse(SPANDAU))
    assert abs(len(alex.cells) - len(spandau.cells)) < 10
    assert alex.usd > 15 * spandau.usd
    assert alex.per_cell > 20 > spandau.per_cell   # one saturates, one does not


def test_overlapping_areas_are_billed_once():
    a = Area.parse(ALEX)
    b = Area.parse("Alex again:52.5219,13.4132:2")
    once = plan_areas([a])
    twice = plan_areas([a, b])
    assert len(twice["distinct_cells"]) == len(once["distinct_cells"])
    assert twice["calls"] == pytest.approx(once["calls"], rel=0.01)


def test_the_free_allowance_applies_to_the_combined_bill():
    r = plan_areas([Area.parse(SPANDAU)])
    assert r["billing"]["usd"] == 0.0                  # under 5,000 calls
    assert r["billing"]["usd_before_free_tier"] > 0


def test_areas_command_prints_and_writes_cells(tmp_path, capsys):
    out = tmp_path / "cells.txt"
    assert main(["areas", "--at", ALEX, "--at", SPANDAU,
                 "--cells-out", str(out)]) == 0
    text = capsys.readouterr().out
    assert "Alexanderplatz" in text and "Spandau" in text and "together" in text
    lines = out.read_text().split()
    assert len(lines) == len(set(lines)) > 200
    assert all(len(x) == 15 for x in lines)


def test_areas_command_needs_at(capsys):
    with pytest.raises(SystemExit):
        main(["areas"])


def test_density_needs_a_census(tmp_path, capsys):
    assert main(["density", "--at", ALEX, "--db", str(tmp_path / "none.db")]) == 1
    assert "Run `allberlin run` first" in capsys.readouterr().err


@pytest.mark.skipif(
    pytest.importorskip("allrestaurants", reason="needs allRestaurants") is None,
    reason="needs allRestaurants")
def test_density_is_measured_from_place_coordinates(tmp_path, capsys):
    """A place found by an edge cell but standing outside the circle is not
    counted; one inside is. That is what the coordinates are for."""
    from berlin.areas import density_from_store
    from berlin.runner import CountStore

    area = Area.parse("Small:52.5219,13.4132:0.5")
    store = CountStore(str(tmp_path / "c.db"))
    cell = cells_in(area)[0]
    inside = {"in1": dict(lat=52.5219, lng=13.4132, types=["cafe"], category="food_drink"),
              "in2": dict(lat=52.5230, lng=13.4140, types=["store"], category="retail")}
    outside = {"out": dict(lat=52.5400, lng=13.4132, types=["store"], category="retail")}
    store.record(cell, 9, {**inside, **outside}, calls=1, depth=0)
    d = density_from_store(store, area)
    store.close()
    assert d.places == 2
    assert d.by_category == {"food_drink": 1, "retail": 1}
    assert d.cells == 1
    main(["density", "--at", "Small:52.5219,13.4132:0.5", "--db", str(tmp_path / "c.db")])
    assert "MEASURED" in capsys.readouterr().out


@pytest.mark.skipif(
    pytest.importorskip("allrestaurants", reason="needs allRestaurants") is None,
    reason="needs allRestaurants")
def test_minimal_export_is_exactly_three_columns(tmp_path, capsys):
    """lat, lng, category. Nothing that identifies a business."""
    import csv
    from berlin.runner import CountStore

    db = tmp_path / "c.db"
    store = CountStore(str(db))
    cell = hexgrid.berlin_cells(9)[5000]
    store.record(cell, 9, {
        "a": dict(lat=52.52, lng=13.41, types=["cafe"], category="food_drink", name="Cafe A"),
        "b": dict(lat=52.53, lng=13.42, types=["park"], category=None, name="Park B"),
    }, calls=1, depth=0)
    store.close()
    out = tmp_path / "min.csv"
    assert main(["export", "--db", str(db), "--out", str(out), "--minimal"]) == 0
    rows = list(csv.reader(out.open()))
    assert rows[0] == ["lat", "lng", "category"]
    assert sorted(r[2] for r in rows[1:]) == ["food_drink", "other"]
    assert all(len(r) == 3 for r in rows)
    assert "Cafe A" not in out.read_text()
