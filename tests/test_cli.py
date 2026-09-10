"""The CLI runs, and says what it is supposed to say."""

import pytest

from berlin.cli import main


@pytest.mark.parametrize("argv", [
    ["plan"], ["cost"], ["skus"], ["types"], ["facts"], ["commands"],
    ["cost", "--min-reviews", "100"], ["cost", "--months", "3"],
    ["plan", "--whole-area"], ["cost", "--tier", "full"],
])
def test_every_command_runs(argv, capsys):
    assert main(argv) == 0
    assert capsys.readouterr().out.strip()


def test_cost_reaches_a_verdict_on_the_free_trial(capsys):
    main(["cost"])
    assert "Free trial" in capsys.readouterr().out


def test_a_higher_bar_reports_a_smaller_bill(capsys):
    main(["cost"])
    low = capsys.readouterr().out
    main(["cost", "--min-reviews", "200"])
    high = capsys.readouterr().out
    assert _headline(low) > _headline(high)


def _headline(text):
    for line in text.splitlines():
        if "after the free tier" in line:
            return float(line.split("$")[1].split()[0].replace(",", ""))
    raise AssertionError("no cost line in output")


def test_commands_writes_a_runnable_script(tmp_path, capsys):
    out = tmp_path / "sweep.sh"
    assert main(["commands", "--out", str(out)]) == 0
    text = out.read_text()
    assert text.startswith("#!/usr/bin/env bash")
    assert "set -euo pipefail" in text
    # One scan per rectangle, and awkward boroughs get more than one.
    from berlin.districts import DISTRICTS
    assert text.count("allrestaurants scan") == sum(len(d.tiles) for d in DISTRICTS)
    assert "--max-requests" in text
    assert "--min-reviews 25" in text
    assert "coffee_shop" in text


def test_the_script_sweeps_cheap_boroughs_first(tmp_path):
    out = tmp_path / "sweep.sh"
    main(["commands", "--out", str(out)])
    order = [line for line in out.read_text().splitlines() if line.startswith("# ")
             and "calls," in line]
    calls = [int(line.split("~")[1].split()[0]) for line in order]
    assert calls == sorted(calls)


def test_types_bare_is_pipeable(capsys):
    assert main(["types", "--bare"]) == 0
    out = capsys.readouterr().out.strip()
    assert "\n" not in out and " " not in out
    assert out.startswith("restaurant,")
