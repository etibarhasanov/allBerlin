"""The taxonomy, whose failure mode is silent and total."""

import pytest

from berlin.entities import (ANCHOR_CATEGORIES, CATEGORIES,
                             MAX_TYPES_PER_REQUEST, PRIVATE_CATEGORIES,
                             Category, by_key, total_private_share,
                             types_argument)


def test_no_category_exceeds_googles_type_limit():
    """Over 50 types and the request is rejected outright -- a whole category
    silently returning nothing is the worst failure available here."""
    for c in CATEGORIES:
        assert len(c.types) <= MAX_TYPES_PER_REQUEST, c.key


def test_the_limit_is_enforced_at_construction():
    with pytest.raises(ValueError):
        Category("x", "X", 0.1, [f"t{i}" for i in range(60)])


def test_private_shares_sum_to_one():
    assert total_private_share() == pytest.approx(1.0)


def test_anchors_are_excluded_from_the_private_total():
    assert {c.key for c in ANCHOR_CATEGORIES} == {"education_childcare", "transport"}
    assert all(c.private for c in PRIVATE_CATEGORIES)


def test_the_types_tallinn_proved_necessary_are_present():
    """Searching 'restaurant' alone missed 22 of 25 curated Tallinn places,
    because Google does not consider a cafe to be a restaurant."""
    food = by_key("food_drink").types
    for t in ("cafe", "coffee_shop", "bakery", "bar", "pub"):
        assert t in food


def test_the_generic_store_type_is_kept():
    """Google's fallback type for a shop it cannot classify. Dropping it
    loses whole streets."""
    assert "store" in by_key("retail").types


def test_no_category_is_empty():
    for c in CATEGORIES:
        assert c.types, c.key


def test_category_keys_are_unique():
    assert len({c.key for c in CATEGORIES}) == len(CATEGORIES)


def test_the_argument_is_a_bare_comma_list():
    arg = types_argument(by_key("health"))
    assert " " not in arg
    assert arg.split(",") == by_key("health").types


def test_lookup_of_an_unknown_category_names_the_known_ones():
    with pytest.raises(KeyError) as exc:
        by_key("nonsense")
    assert "food_drink" in str(exc.value)
