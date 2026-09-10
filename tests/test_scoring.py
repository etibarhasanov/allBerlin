"""Turning counts into scores: normalisation, catchments, and profiles."""

import pytest

from berlin import hexgrid
from berlin.scoring import (PROFILES, Features, build_features,
                            percentile_ranks, profile, score_cells,
                            shannon_diversity, top_cells)


def test_percentile_ranks_span_zero_to_one():
    assert percentile_ranks([1, 2, 3, 4]) == [0.0, 1 / 3, 2 / 3, 1.0]


def test_ties_share_a_rank_rather_than_being_broken_arbitrarily():
    """Most cells hold zero of any given category. Breaking those ties would
    make the bottom half of every score noise presented as signal."""
    ranks = percentile_ranks([0, 0, 0, 9])
    assert ranks[0] == ranks[1] == ranks[2]
    assert ranks[3] == 1.0


def test_percentile_ranks_handle_the_degenerate_cases():
    assert percentile_ranks([]) == []
    assert percentile_ranks([5]) == [0.5]
    assert percentile_ranks([7, 7]) == [0.5, 0.5]


def test_ranks_are_immune_to_the_skew_that_would_break_a_z_score():
    """One cell a thousand times the rest must not flatten everything else."""
    ranks = percentile_ranks([1, 2, 3, 4, 5000])
    assert ranks[:4] == [0.0, 0.25, 0.5, 0.75]


def test_diversity_separates_a_monoculture_from_a_mix():
    assert shannon_diversity({"a": 50}) == 0.0
    assert shannon_diversity({"a": 25, "b": 25}) == pytest.approx(1.0)
    assert 0 < shannon_diversity({"a": 45, "b": 5}) < 1


def test_diversity_of_nothing_is_zero_not_an_error():
    assert shannon_diversity({}) == 0.0
    assert shannon_diversity({"a": 0, "b": 0}) == 0.0


def _three_cells():
    a = hexgrid.berlin_cells(9)[5000]
    neighbours = [c for c in hexgrid.ring(a, 1) if c != a]
    return a, neighbours


def test_catchment_sums_the_ring_including_the_cell_itself():
    a, neighbours = _three_cells()
    counts = {a: {"retail": 5}}
    counts.update({n: {"retail": 2} for n in neighbours})
    features = {f.cell: f for f in build_features(counts, rings=(1,))}
    assert features[a].catchment[1] == 5 + 6 * 2


def test_missing_neighbours_count_as_empty_not_as_absent():
    """A site on the city edge genuinely has less around it. Dropping the
    missing neighbours would flatter it into looking central."""
    a, _ = _three_cells()
    features = build_features({a: {"retail": 5}}, rings=(1,))
    assert features[0].catchment[1] == 5


def test_anchors_are_not_counted_as_private_entities():
    a, _ = _three_cells()
    features = build_features({a: {"retail": 4, "transport": 9}}, rings=(1,))
    assert features[0].total == 4


def test_a_profile_penalty_can_outweigh_its_rewards():
    """Without this a profile cannot express competition, which is most of
    what site selection is."""
    p = profile("retail_site")
    crowded = p.score({"catchment_k1": 1.0, "transport": 1.0, "diversity": 1.0,
                       "count_food_drink": 1.0, "count_retail": 1.0})
    clear = p.score({"catchment_k1": 1.0, "transport": 1.0, "diversity": 1.0,
                     "count_food_drink": 1.0, "count_retail": 0.0})
    assert clear > crowded


def test_scores_stay_inside_zero_and_one():
    for p in PROFILES.values():
        assert p.score({f: 1.0 for f in p.weights}) <= 1.0
        assert p.score({f: 1.0 for f in p.penalties}) >= 0.0


def test_every_profile_scores_the_modelled_city():
    from berlin.census import modelled_counts, modelled_population
    counts = modelled_counts(8)
    features = build_features(counts, rings=(1, 2),
                              population=modelled_population(8))
    for key in PROFILES:
        scores = score_cells(features, profile(key))
        assert len(scores) == len(counts)
        assert all(0.0 <= v <= 1.0 for v in scores.values())


def test_footfall_peaks_in_the_middle_of_berlin():
    from berlin.census import modelled_counts
    features = build_features(modelled_counts(8), rings=(1,))
    scores = score_cells(features, profile("footfall"))
    best = top_cells(scores, 1)[0][0]
    lat, lng = hexgrid.cell_center(best)
    assert abs(lat - 52.52) < 0.05 and abs(lng - 13.40) < 0.08


def test_underserved_does_not_peak_in_the_middle_of_berlin():
    """If it did, the profile would be measuring supply twice and calling one
    of them demand."""
    from berlin.census import modelled_counts, modelled_population
    features = build_features(modelled_counts(8), rings=(1, 2),
                              population=modelled_population(8))
    scores = score_cells(features, profile("underserved"))
    best = top_cells(scores, 1)[0][0]
    lat, lng = hexgrid.cell_center(best)
    assert abs(lat - 52.52) > 0.03 or abs(lng - 13.40) > 0.05


def test_an_unknown_feature_is_an_error_not_a_zero():
    f = Features(cell="x", counts={}, total=0, diversity=0, catchment={},
                 transport=0, education=0)
    with pytest.raises(KeyError):
        f.get("count_of_unicorns_nearby")


def test_an_unknown_profile_names_the_known_ones():
    with pytest.raises(KeyError) as exc:
        profile("vibes")
    assert "footfall" in str(exc.value)
