"""The type filter, which is where the Tallinn sweep went wrong first."""

from berlin.sweep import BERLIN_EXTRA_TYPES, TALLINN_TYPES, TYPES, types_argument


def test_the_types_that_were_missing_in_tallinn_are_all_here():
    """Cafes, bakeries, pubs and bars accounted for 22 of 25 Tallinn misses."""
    for t in ("cafe", "coffee_shop", "bakery", "bar", "pub", "chocolate_shop"):
        assert t in TYPES


def test_berlin_specific_types_are_added():
    """Doener and Imbiss type as fast food or takeaway, not as restaurants."""
    for t in ("fast_food_restaurant", "meal_takeaway"):
        assert t in TYPES


def test_no_duplicates():
    assert len(TYPES) == len(set(TYPES))
    assert not set(TALLINN_TYPES) & set(BERLIN_EXTRA_TYPES)


def test_the_argument_is_a_bare_comma_list():
    arg = types_argument()
    assert " " not in arg
    assert arg.split(",") == TYPES


def test_within_the_api_limit():
    """Nearby Search caps includedTypes at 50."""
    assert len(TYPES) <= 50
