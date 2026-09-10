"""The borough table against Berlin's published figures."""

import pytest

from berlin.districts import (BERLIN_AREA_KM2, BERLIN_POPULATION, DISTRICTS,
                              by_name, total_area_km2, total_expected_places,
                              total_population, total_settled_km2,
                              total_swept_km2)


def test_areas_sum_to_berlin():
    assert total_area_km2() == pytest.approx(BERLIN_AREA_KM2, abs=0.5)


def test_populations_sum_to_berlin():
    assert total_population() == pytest.approx(BERLIN_POPULATION, rel=0.01)


def test_all_twelve_boroughs_are_present():
    assert len(DISTRICTS) == 12
    assert len({d.name for d in DISTRICTS}) == 12


def test_settled_ground_is_about_half_the_city():
    """Berlin is roughly 18% forest and 7% water; a sweep should skip both."""
    share = total_settled_km2() / total_area_km2()
    assert 0.45 < share < 0.65


def test_expected_places_land_in_the_published_range():
    """Sources put Berlin's eateries between 7,000 and 13,000; 25+ reviews
    should sit inside that, not above it."""
    assert 7_000 < total_expected_places() < 13_000


def test_density_ordering_matches_the_city():
    """Kreuzberg and Mitte densest, the outer estates thinnest -- if the
    modelled factors ever stop producing that, they are wrong."""
    ranked = sorted(DISTRICTS, key=lambda d: -d.density)
    assert {ranked[0].name, ranked[1].name} == {
        "Mitte", "Friedrichshain-Kreuzberg"}
    assert ranked[-1].name in {"Marzahn-Hellersdorf", "Treptow-Koepenick"}


def test_tiles_are_well_formed_and_inside_berlin():
    for d in DISTRICTS:
        for south, west, north, east in d.tiles:
            assert south < north and west < east, d.name
            assert 52.33 <= south < north <= 52.68, d.name
            assert 13.08 <= west < east <= 13.77, d.name


def test_every_centre_falls_inside_one_of_its_own_tiles():
    """The centre is what `allrestaurants check` probes; a centre outside the
    swept rectangles would measure a density the sweep never sees."""
    for d in DISTRICTS:
        lat, lng = d.center
        assert any(s <= lat <= n and w <= lng <= e for s, w, n, e in d.tiles), d.name


def test_tiles_cover_the_settled_ground_without_covering_the_city_twice():
    """Loose enough to contain the built-up borough, tight enough that the
    lakes and forest are not being paid for."""
    for d in DISTRICTS:
        assert d.swept_km2 >= d.settled_km2, d.name
        assert d.swept_km2 / d.settled_km2 < 1.6, d.name
    assert total_swept_km2() < total_area_km2()


def test_lookup_forgives_spelling():
    assert by_name("mitte").name == "Mitte"
    assert by_name("Neukölln").name == "Neukoelln"
    assert by_name("friedrichshain-kreuzberg").name == "Friedrichshain-Kreuzberg"
    with pytest.raises(KeyError):
        by_name("Hamburg")
