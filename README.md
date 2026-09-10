# allBerlin

A count of every private entity in Berlin, on a hexagonal grid, as the base
layer for a location intelligence scoring product.

Not a directory — a **surface**. For each cell you get how many businesses
stand within a two-minute walk of it, broken down by what kind, plus the same
for the ring around it. From that you can ask the only question a location
product is really asked: *is this a good place to put this thing, and compared
to what?*

```bash
git clone <this repo> && cd allBerlin
pip install -e .

allberlin grid            # the hex resolutions, and what each one is for
allberlin census          # calls and hours for a full count of Berlin
allberlin cost            # the money answer
allberlin score --profile food_site
allberlin run             # make the calls (needs a Google Maps key)
```

---

## The answer

**It is free.** About **122,000 API calls**, **3.4 hours** of wall clock, and
**$0.00**.

| | cells | calls | hours | cost |
|---|---|---|---|---|
| res 8 — a district view | 1,454 | 27,929 | 0.8 | **$0.00** |
| **res 9 — a five-minute walk** | **10,155** | **122,274** | **3.4** | **$0.00** |
| res 10 — a block | 71,114 | 853,368 | 23.7 | **$0.00** |

That is twelve categories swept across the whole city, at a modelled **119,700
private entities**. Nothing is spent against the $300 free trial credit, which
stays available for whatever you want detail on later.

The reason is one SKU. **Nearby Search Essentials (IDs Only)** returns place
ids and nothing else — no name, no address, no coordinates, no rating — and
Google prices it at $0.00 with **no monthly cap at all**, unlike the 1,000
free Enterprise calls that a review-bearing sweep gets. A count product needs
exactly that and nothing more. There is no second stage to pay for, because
**the count is the product**.

Worth being precise about how that inverts the answer for the other kind of
dataset. If you want ratings per place, IDs-Only is a trap: an id carries no
review count, so the review bar has nothing to read, the sweep has to run as a
full census anyway, and then you pay $20 per 1,000 for Place Details on every
id it turned up, one place per call, to find out what you collected. That path
costs about $2,000 for Berlin. Counting skips the whole second half.

**What you would pay if you wanted more than a count:**

| | |
|---|---|
| the same sweep at Pro — name, address, location, types | $3,753 |
| Place Details Pro afterwards, one call per place | $1,950 |
| census everything free, then re-sweep 100 chosen cells at Pro | **$3.20** |

The last row is the one to plan on. Count everything for nothing; buy detail
only where a decision actually turns on it.

## Why hexagons

Every cell has six neighbours at one distance. A square grid has four edge
neighbours and four corner ones 1.41× further away, and every "what is around
here" question then has to pick a lie to tell about that. Since a location
score is almost entirely a statement about a *neighbourhood*, a grid that
distorts neighbourhoods distorts the product.

A k-ring is 3k(k+1)+1 cells — 7, 19, 37 — and that is the whole catchment
arithmetic. [H3](https://h3geo.org) is also a global standard index, so a cell
id means the same thing here as in whatever you join the scores against later.

Resolution is a **product decision, not a cost optimisation**. Minimising calls
alone would pick res 8 every time, because breaking a saturated cell is cheaper
than laying seven cells where one would do — but breaking a cell does not make
the grid finer. Everything found still belongs to the cell being broken, so res
8 gives 0.74 km² granularity however hard it works, and 0.74 km² is a
neighbourhood, not a site.

| res | cell | across | what it is |
|---|---|---|---|
| 8 | 0.74 km² | 531 m | a district view |
| **9** | **0.105 km²** | **201 m** | **a five-minute walk — the default** |
| 10 | 0.015 km² | 76 m | a block, for siting one door |

## The part that is easy to get wrong

Google's Nearby Search takes a circle, so each cell is queried as the circle
that circumscribes it. And it returns **at most 20 results** whatever the
circle holds, so a cell in Mitte will come back full and hiding more.

The obvious fix — split the circle into four smaller ones, which is what
[allRestaurants](https://github.com/etibarhasanov/allRestaurants) does — is
wrong here, and quietly. Those four children sit at (±r/2, ±r/2) with radius
r/√2, so they reach **1.43r** from the centre and drag in places from well
outside the cell they are supposed to be measuring. Measured on a test clump:
**75 places returned for a circle holding 62**, a 21% over-count. And it cannot
be cleaned up afterwards, because an IDs-Only response has no coordinates to
filter on. Every count in the product would be inflated, worst exactly where
density is highest.

So saturation is broken by **splitting the type list instead of the circle**. A
cell returning 20 for thirty retail types is asked again for fifteen of them,
and again for the other fifteen, against the *identical circle*. Every result
is still exactly where it was, the union is complete, the count stays exact —
and the subsets are useful in their own right, because they are finer
categories. Measured against clumps from 1.2× to 15× the cap:

| over the cap | 1.2× | 2.0× | 3.0× | 4.5× | 7.0× | 10× | 15× |
|---|---|---|---|---|---|---|---|
| extra calls | 2 | 4 | 6 | 14 | 20 | 30 | 58 |
| count exact | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |

3.75 extra calls per multiple of the cap, and exact every time. Only when a
*single* type still saturates does geometry have to move, and then the cell
descends to its seven H3 children and is **flagged inexact** in the store
rather than reported alongside the clean ones.

The ids are kept per cell, not just totals. Neighbouring circles overlap by
about a fifth, so a city total taken by adding cell counts would double-count
the seams — with ids it is a set union, and exact. Free calls still buy that.

## From counts to a score

Three things stand between a count and a score, and each is a decision that
should be visible rather than buried in a weighting.

**Neighbourhood.** What matters at a site is not what is in its own 0.1 km²
cell but what is within a walk. Every feature has a catchment form summed over
the k-ring.

**Comparability.** Raw counts are not comparable across features and their
distributions are badly skewed — a mean-and-standard-deviation normalisation
would be dominated by the top hundred cells in Mitte. Features become
**percentile ranks** across the city: scale-free, robust to the skew, and
readable. 0.9 means denser than 90% of Berlin. Ties share a rank, which matters
because most cells hold zero of any given category and breaking those ties
would make the bottom half of every score noise presented as signal.

**Purpose.** There is no single good location. A site is good *for something*,
so there is no default score — there are profiles, each a set of weights **and
penalties**. A profile that cannot say "too much of this is bad" cannot express
competition, and competition is most of what site selection is.

| profile | question |
|---|---|
| `footfall` | Where are people already passing? |
| `retail_site` | Where would a new shop trade well? *(penalises existing retail)* |
| `food_site` | Where would a new cafe trade well? *(penalises existing food)* |
| `underserved` | Where do residents live with the least around them? |
| `office` | Where is the weekday, daytime economy? |

```
$ allberlin score --profile food_site --top 3
  rewards : catchment_k1 x1.0, transport x0.8, count_retail x0.4, ...
  punishes: count_food_drink x0.6
```

`allberlin score` runs the whole pipeline against the **modelled** surface, so
you can see the shape of the output before an API key is involved. It says so
loudly every time. The model is smooth by construction and deliberately not
roughened with plausible-looking noise, because a surface that looked like data
would invite being used as data.

## What is measured and what is modelled

The load-bearing distinction in the whole repo:

| | source |
|---|---|
| H3 geometry, cell counts, ring sizes | **Exact** — computed |
| SKU prices and free allowances | Google's pricing pages, September 2026 |
| Type-splitting call cost (3.75 per excess multiple) | **Measured** against the splitter |
| Quadtree over-count (21%) | **Measured** against a known clump |
| Berlin registered companies (190,000) | Published |
| Mappable share (63%) | **Estimated** |
| Commercial intensity per borough | **Estimated** |
| Density gradient from the centre | **Estimated** — standard monocentric form |
| Category shares of all entities | **Estimated** — replaced by the census itself |

Everything after `allberlin run` is measured. Everything before it exists only
to size the run and to let the pipeline be tested without one.

One cross-check does hold, and it is in the test suite. This model reaches
Berlin's eateries through registered-company counts and gets **16,758**. The
independent review-bar model in `berlin/cost.py` reaches them through Tallinn's
measured gastronomy rate and gets **10,649 with 25+ reviews**. Two different
routes, no shared inputs, and the second sits sensibly inside the first.

## Running it

```bash
export GOOGLE_MAPS_API_KEY=...

allberlin run --limit 50 --category food_drink     # a first look, ~50 calls
allberlin run --res 9                              # the whole city
```

Restrict the key to **Places API (New)**, and note that the field mask is fixed
at the ids tier in `runner.py` — that is the economic argument, not a default,
so it is not exposed as a flag. Cells already done are skipped on a re-run:
free calls still cost hours.

Results land in `data/berlin_census.db`: `cell_census` for counts, `cell_places`
for the ids behind them, both keyed by H3 cell.

## Layout

| Module | Role |
|---|---|
| `berlin/geometry.py` | Berlin's outline — the bounding box is 1.9× the city |
| `berlin/hexgrid.py` | H3 grid, cell → query circle, k-rings, resolutions |
| `berlin/entities.py` | What counts as a private entity, in Google's type vocabulary |
| `berlin/census.py` | Calls, hours, density model, the modelled surface |
| `berlin/runner.py` | The census itself: type-splitting, exact counts, resume |
| `berlin/scoring.py` | Features, percentile ranks, profiles |
| `berlin/cost.py` | The paid alternative: a review-bearing sweep, priced |
| `berlin/districts.py` | Boroughs — area, population, built-up share |

## Tests

```bash
pip install -e ".[dev]" && pytest
```

133 tests, no network. The ones that carry weight: that type-splitting returns
the **exact** count at 25, 40, 90 and 200 places in a cell; that it never moves
the circle; that ids deduplicate across the seam between neighbouring cells
where naive addition inflates; that the density surface integrates to the
modelled total; that a profile's penalty can outweigh its rewards; and that
`underserved` does **not** peak in the middle of Berlin, which it would if the
profile were measuring supply twice and calling one of them demand.

## Terms of service

Google allows place ids to be cached **indefinitely**, which is unusually
convenient here: ids are the entire dataset. The 30-day limit applies to
content — names, ratings, addresses — and this collects none of it. A count
derived from ids is your own derived statistic, but if the counts are going to
be sold as a product rather than used internally, read
[the Maps Platform terms](https://cloud.google.com/maps-platform/terms)
sections 3.2.3 and 3.2.4 and get it reviewed.
