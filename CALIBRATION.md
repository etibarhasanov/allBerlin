# Where `calls ≈ 5.0 × √(places × area)` comes from

The estimate in allRestaurants assumes every saturated circle splits into four.
That is a reasonable-sounding rule and it has already been wrong once, by a
factor of 1.7 in the expensive direction: it priced Tallinn's district passes at
286 calls against an actual 171. Twelve probe calls found the error and cost
$0.42.

It cannot be right in general, because splitting is driven by how restaurants
clump together and a grid does not know where the clumps are. Pricing Berlin on
it would have meant pricing a city nobody has swept using a rule already known
to be wrong on the one city that has been.

So this was measured instead.

## Method

`tools/calibrate.py` replays the **real** `Sweeper` from allRestaurants — the
real splitting rule, the real 20-result cap, the real review bar, the real
resume log — against a fake Nearby Search backed by the **real** 1,110 Tallinn
coordinates in `exports/tallinn_restaurants.csv`. The fake returns the twenty
highest-reviewed places inside the circle, which is what Google's POPULARITY
ranking does and what the stopping rule reads.

Berlin is denser than Tallinn, so the point set is thickened two-, four- and
eightfold. Copies land on an 80 m gaussian around their original, so the
clustering survives — an evenly spread city would be far cheaper to sweep than
any real one, and calibrating on one would understate everything downstream.

No network, no API key, no money:

```bash
python3 tools/calibrate.py --allrestaurants ../allRestaurants
```

## What it measured

Cheapest starting radius at each density, over Tallinn's 207 km² bbox:

| density × | places | per km² | best cell | calls | recall | calls/km² | calls/place | constant |
|---|---|---|---|---|---|---|---|---|
| 1 | 1,110 | 5.4 | 400 m | 2,390 | 100.0% | 11.56 | 2.15 | 4.99 |
| 2 | 2,220 | 10.7 | 250 m | 3,625 | 99.3% | 17.53 | 1.63 | 5.35 |
| 4 | 4,440 | 21.5 | 200 m | 4,660 | 93.5% | 22.53 | 1.05 | 4.86 |
| 8 | 8,880 | 42.9 | 150 m | 6,708 | 81.7% | 32.44 | 0.76 | 4.95 |

The constant is `calls / √(places × area_km²)`. Over an eightfold density range
it moves between 4.86 and 5.35 — a spread of 6.2% about a mean of 5.04.

## Why the geometric mean

Neither term alone predicts anything useful.

**Not area.** An empty square kilometre costs exactly one call. Tallinn's 207
km² bbox is mostly the Gulf of Finland, Lake Ülemiste and forest, and those
parts are nearly free. Cost per km² rose from 11.6 to 32.4 across the range
above, so a per-km² rate fitted anywhere is wrong everywhere else.

**Not the place count either** — and this one is counter-intuitive. Calls per
place *fall* as density rises, from 2.15 to 0.76. A circle returns up to twenty
places for one call, so a dense circle is better value than a sparse one: the
expensive city is not the one with the most restaurants, it is the one that
spreads them out.

Cost follows the two together. `√(places × area)` is, up to the constant, the
number of circles you need when circle size is chosen to suit local density —
which is what the sweep converges on by splitting.

## Three things the measurement does not cover

**Recall falls at the top of the range.** At eightfold density the sweep found
82% of the point set, not 100%. That is an artefact of the thickening: eight
copies inside an 80 m gaussian is tighter than real restaurants pack, and the
splitter hits its 40 m radius floor before it can separate them. Real cities do
not stack that way — but it does mean the constant at the dense end is measured
against a sweep that stopped early, so it reads slightly low there.

**Census mode is a different algorithm, not a denser one.** With no review bar
there is no brake: every full circle splits until nothing saturates. Extending
the fitted curve into census mode understates it about fivefold, so
`berlin/cost.py` prices census off the ratio actually measured between the two
modes on the allRestaurants fixture — 2,176 calls against 358 — rather than off
the curve.

**A wider type filter saturates circles sooner.** The calibration runs on data
collected with the wide Berlin-style type list, so the two match. Sweeping with
`--types restaurant` alone would be cheaper per km² and would miss every café,
bakery, pub and bar — 22 of 25 misses when Tallinn tried it.

## The non-monotonic column

Read the full output rather than just the best row and one thing stands out:
cost does not fall smoothly as circles shrink. At base density, 250 m cost
2,521 calls, 300 m cost 2,722, and 400 m cost 2,390 — a coarser grid beating a
finer one that beats a coarser one still. It is purely how the grid happens to
land on the clusters.

Treat any single figure as indicative, not a law. The constant is a fit across
twenty-four runs, and it is quoted with a 25% contingency downstream for
exactly this reason.

## The run itself

`calibration-run.txt` in this repo is the verbatim output of

```bash
python3 tools/calibrate.py --allrestaurants ../allRestaurants
```

against `exports/tallinn_restaurants.csv` at commit `05f97f6`. Twenty-four
replays, no network, about four minutes. It ends:

```
calls ~= 5.04 * sqrt(places * area_km2)
  per-density constants: 4.99, 5.35, 4.86, 4.95
  spread about the mean: 6.2%
```

`berlin/cost.py` rounds that to 5.0.
