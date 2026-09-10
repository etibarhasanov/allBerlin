"""The CLI runs, and the commands that make claims make the right ones."""

import pytest

from berlin.cli import main


@pytest.mark.parametrize("argv", [
    ["grid"], ["categories"], ["categories", "--category", "retail"],
    ["census"], ["census", "--res", "8"], ["cost"], ["cost", "--months", "2"],
    ["profiles"], ["facts"],
    ["skus"], ["score", "--profile", "footfall", "--res", "8"],
    ["score", "--profile", "underserved", "--res", "8", "--top", "3"],
])
def test_every_command_runs(argv, capsys):
    assert main(argv) == 0
    assert capsys.readouterr().out.strip()


def test_cost_prices_both_routes_and_names_the_caveat(capsys):
    main(["cost"])
    out = capsys.readouterr().out
    assert "ROUTE A" in out and "Nearby Search Pro" in out
    assert "ROUTE B" in out and "Text Search Essentials (IDs Only)" in out
    assert "CAVEAT" in out
    assert "$0.00" not in out.split("ROUTE B")[0]   # Route A is not free


def test_cost_owns_the_earlier_mistake(capsys):
    """The $0 figure was published. The correction should be as visible."""
    main(["cost"])
    out = capsys.readouterr().out
    assert "no free Nearby Search tier" in out
    assert "was wrong" in out


def test_export_without_a_census_fails_cleanly(tmp_path, capsys):
    assert main(["export", "--db", str(tmp_path / "none.db"),
                 "--out", str(tmp_path / "x.csv")]) == 1
    assert "Run `allberlin run` first" in capsys.readouterr().err


def test_score_says_loudly_that_it_is_modelled(capsys):
    main(["score", "--res", "8"])
    out = capsys.readouterr().out
    assert "MODELLED, NOT MEASURED" in out


def test_score_shows_the_weights_it_used(capsys):
    """A score nobody can audit is a number, not a product."""
    main(["score", "--profile", "retail_site", "--res", "8"])
    out = capsys.readouterr().out
    assert "rewards" in out and "punishes" in out


def test_run_without_a_key_fails_cleanly(capsys, monkeypatch):
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    assert main(["run", "--res", "8", "--limit", "1"]) == 1
    assert "API key" in capsys.readouterr().err


def test_census_offers_the_other_resolutions(capsys):
    main(["census", "--res", "9"])
    out = capsys.readouterr().out
    assert "res 8:" in out and "res 10:" in out


def test_categories_lists_the_full_type_list_on_request(capsys):
    main(["categories", "--category", "food_drink"])
    out = capsys.readouterr().out
    assert "coffee_shop" in out
