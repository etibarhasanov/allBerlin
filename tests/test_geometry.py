"""The Berlin outline, which every cell count depends on."""

import pytest

from berlin.geometry import (BERLIN_AREA_KM2, BERLIN_OUTLINE, berlin_area_km2,
                             berlin_bbox_area_km2, bbox, contains,
                             polygon_area_km2)


def test_the_outline_is_about_the_right_size():
    """Coarse on purpose, but not wrong: within 10% of the official area."""
    assert berlin_area_km2() == pytest.approx(BERLIN_AREA_KM2, rel=0.10)


def test_the_outline_errs_generous_rather_than_short():
    """Excess sits on the border, which is the cheapest ground there is --
    an empty cell costs one call. A short polygon would silently miss city."""
    assert berlin_area_km2() > BERLIN_AREA_KM2


def test_the_bounding_box_is_nearly_twice_the_city():
    """The entire reason for carrying a polygon instead of four numbers."""
    assert berlin_bbox_area_km2() > 1.8 * BERLIN_AREA_KM2


def test_the_extreme_points_are_on_the_outline():
    south, west, north, east = bbox(BERLIN_OUTLINE)
    assert north == pytest.approx(52.6755, abs=0.001)   # Frohnau
    assert south == pytest.approx(52.3382, abs=0.001)   # Lichtenrade
    assert west == pytest.approx(13.0884, abs=0.001)    # Staaken
    assert east == pytest.approx(13.7612, abs=0.001)    # Muggelheim


@pytest.mark.parametrize("name,lat,lng", [
    ("Alexanderplatz", 52.5219, 13.4132),
    ("Kottbusser Tor", 52.4990, 13.4180),
    ("Spandau Altstadt", 52.5370, 13.2000),
    ("Koepenick", 52.4450, 13.5800),
    ("Tegel", 52.5900, 13.2900),
])
def test_places_in_berlin_are_inside(name, lat, lng):
    assert contains(BERLIN_OUTLINE, lat, lng), name


@pytest.mark.parametrize("name,lat,lng", [
    ("Potsdam", 52.3906, 13.0645),
    ("Oranienburg", 52.7550, 13.2360),
    ("Konigs Wusterhausen", 52.2940, 13.6220),
    ("Bernau", 52.6790, 13.5870),
])
def test_places_outside_berlin_are_outside(name, lat, lng):
    assert not contains(BERLIN_OUTLINE, lat, lng), name


def test_a_square_has_the_area_of_a_square():
    """Roughly 1 km on a side at Berlin's latitude."""
    d_lat = 1.0 / 111.320
    d_lng = 1.0 / (111.320 * 0.6087)
    square = [(52.5, 13.4), (52.5, 13.4 + d_lng),
              (52.5 + d_lat, 13.4 + d_lng), (52.5 + d_lat, 13.4)]
    assert polygon_area_km2(square) == pytest.approx(1.0, rel=0.02)


def test_a_degenerate_polygon_is_refused():
    with pytest.raises(ValueError):
        polygon_area_km2([(52.5, 13.4), (52.6, 13.5)])
