# allBerlin

What it costs to collect every eatery in Berlin from Google Maps — with its
rating and review count — and how to run it.

The collection itself is [allRestaurants][ar]: circles tiled across a city,
each split where it saturates. This repo is the part that has to happen before
you spend anything — which ground to sweep, at what circle size, for how many
calls, against which Google SKU, and whether the free trial swallows it.

[ar]: https://github.com/etibarhasanov/allRestaurants

```bash
git clone <this repo> && cd allBerlin
pip install -e .

allberlin cost          # the money answer
allberlin plan          # per-borough call counts
allberlin commands      # the sweep script to run
```

---

## The answer

**About 10,900 API calls and $347 for a one-off sweep of Berlin.**

Not free, but close enough that the choices below decide it:

| | calls | cost |
|---|---|---|
| Berlin, 25+ reviews | 10,918 | **$347** |
| …spread over two calendar months | 10,918 | **$312** |
| …at a 100-review bar instead | 9,307 | **$291** |
| …both together | 9,307 | **$256** |
| …with 25% contingency, one month | 13,647 | $443 |
| Tiling the lakes and forest too | 13,776 | $447 |
| Census — every place, no review bar | 64,700 | $2,230 |

Google's free trial is **$300 in credits over 90 days** for a new billing
account. The headline $347 overshoots it by $47. A 100-review bar, or simply
letting the run cross a month boundary, brings it inside; do both and there is
$44 of headroom left for the mistakes.

What you get for that: name, Google Maps link, address, coordinates, **rating
and review count**, price level, phone, website, opening hours and service
attributes, for every place in Berlin carrying at least 25 reviews — about
**10,600 places**.

## Where each number comes from

**$35 per 1,000 calls.** Review counts sit in Google's *Enterprise* field tier,
and a request bills at the highest tier any field in its mask touches. One
review count on an otherwise-Pro call prices the whole call at Enterprise.
There is no partial billing, so review counts cost $35/1,000 rather than the
$32 the same call would cost without them. Review *text* would be Enterprise +
Atmosphere at $40 — see "Reviews, and which kind" below.

**1,000 free calls, not $200 of them.** Google retired the pooled $200 monthly
credit on 1 March 2025. Each SKU now has its own monthly free count — 10,000
Essentials, 5,000 Pro, **1,000 Enterprise** — and they neither pool nor roll
over. A sweep that would have been free under the old credit now gets 1,000
calls, worth $35.

**10,918 calls.** Not a guess, and not the old "assume every dense circle
splits into four" rule — that rule already priced Tallinn's districts at 286
calls against an actual 171. Instead the real sweep was replayed offline over
the 1,110 real Tallinn coordinates, thickened up to eightfold to stand in for a
denser city, and measured. Across an eightfold density range the cost collapses
to one line:

```
calls  ≈  5.0 × √(places × area_km²)
```

The geometric mean is the finding. Cost follows neither term alone: an empty
square kilometre costs one call, and a *denser* city returns more places per
call — calls per place fell from 2.15 in Tallinn to 0.77 at eight times its
density. It follows the two together, and the constant held within 7% at every
density measured. Reproduce it with `python3 tools/calibrate.py` — no network,
no key, no money. Details in [CALIBRATION.md](CALIBRATION.md).

**10,649 places.** Tallinn's sweep found 1,110 places with 25+ reviews among
461,000 residents. Applying that rate to each Berlin borough's population,
weighted by how much gastronomy the borough carries per resident — Mitte 2.6×
the city average, Marzahn-Hellersdorf 0.5× — gives 10,649. Published counts for
Berlin range from 7,000 to 13,000 eateries depending on what is being counted,
so this lands mid-range rather than at an edge.

**645 km² swept, not 892 — and not 1,925.** Berlin is 18% forest and 7% water,
and only about 485 km² of it is built up. Tiling a lake costs what tiling
Kreuzberg costs and returns nothing, so each borough is swept as one to three
rectangles around its built-up parts rather than as one rectangle around the
whole borough. Treptow-Köpenick shows why: a single box around it is 446 km²
for a 168 km² borough, most of it the Müggelsee. Three boxes cover it in 74.

That leaves 161 km² of lake, forest and borough fringe inside the rectangles
anyway, and pricing it right matters. The geometric-mean law assumes circle
size is tuned to density, and empty ground has none: what actually happens is
one call, no results, no split. The 161 km² costs **327 calls**, not the 1,900
the law would have charged for it. Overhead is 3% of the bill, which is the
test that says the rectangles are tight enough.

## Why not the free SKU

Nearby Search Essentials (IDs Only) is genuinely $0.00 with no monthly cap,
which invites an obvious plan: discover everything for free, buy details only
for what you want. It does not work, for two compounding reasons.

An IDs-only response carries no review count, so the stopping rule has nothing
to read — the sweep has to run as a census, splitting every full circle until
nothing saturates. On the allRestaurants fixture that was 2,176 calls against
358. They are free calls, so far so good.

But a census finds everything, and most of everything is the long tail below
the review bar: about 37,000 IDs instead of 10,600, with no way to tell which
is which until you pay. Place Details Enterprise is **$20 per 1,000 — one
place per call**, against $35 per 1,000 for a Nearby Search call that returns
**twenty**. That is $0.0200 a place against $0.0018. The free discovery saves
$336 and creates a $740 bill.

`allberlin skus` prints the full comparison.

## Reviews, and which kind

Two different things get called "the reviews", and they are priced and
regulated differently.

- **Rating and review count** — 4.6 stars, 812 reviews. Enterprise tier,
  $35/1,000 as a Nearby Search field. This is what the sweep collects, what the
  review bar filters on, and what makes a place worth approaching or not.
- **Review text** — the written reviews themselves, five per place at most.
  Enterprise + Atmosphere, $40/1,000, and they carry display and attribution
  obligations that a CRM copy will not satisfy on its own.

This repo prices and plans the first. `--tier full` prices the second if you
want to see the difference; it is about $48 more across Berlin, and the
constraint on it is not the money.

## Keeping it current

Google allows caching place IDs indefinitely and the content attached to them
for roughly 30 days. A live dataset therefore needs re-collecting monthly, and
at Berlin's size the cheaper refresh is *not* another sweep:

| refresh | monthly |
|---|---|
| re-sweep from scratch | $347 |
| Place Details on the 10,649 IDs you already hold | **$193** |

The crossover is the point at which discovery costs more than one call per
place — which for Berlin it does, by a wide margin. `allrestaurants prune
--older-than-days 30` clears stale content while keeping the IDs.

## Before you spend anything

Twelve probe calls on Tallinn's districts cut a 286-call estimate to 171 and
cost $0.42. The same move applies here, and the borough factors in
`berlin/districts.py` are exactly the kind of estimate a probe replaces:

```bash
TYPES=$(allberlin types --bare)
allrestaurants check --center "52.5200,13.4050" --types "$TYPES"   # Mitte
allrestaurants check --center "52.5350,13.5900" --types "$TYPES"   # Marzahn
```

What the probe reads is the *weakest of the 20 results*. If even that one
clears the review bar, the circle is hiding more and will split — this is a
borough that will cost. If the twentieth result has 6 reviews, the tail is
already in view and the circle stops without splitting. Tallinn's Kesklinn came
back with a twentieth result at 0 reviews and cost nothing extra; Old Town's
was at 565, and Old Town was the only genuinely expensive district in the city.

Then sweep, cheapest borough first, so that a budget running out leaves the
expensive part as a decision rather than a random half of a city:

```bash
allberlin commands --out sweep.sh && bash sweep.sh
```

Every borough is resumable — rerunning the identical command picks up where it
stopped rather than paying Google twice.

## What is modelled and what is measured

Worth being blunt about, because the model is only as good as its weakest
input:

| | source |
|---|---|
| Borough areas and populations | Official, Amt für Statistik Berlin-Brandenburg |
| SKU prices and free allowances | Google's pricing pages, September 2026 |
| calls ≈ 5.0 × √(places × area) | **Measured** by replaying the real sweep on real Tallinn data |
| Empty-ground overhead | Derived from allRestaurants' own grid spacing |
| Review-bar shares (50+, 100+, 200+) | **Measured** on the 1,110 Tallinn places |
| Census multiplier (6.1×) | **Measured** on the allRestaurants fixture |
| Eateries per 1,000 residents (2.41) | Measured in Tallinn, *assumed* to transfer to Berlin |
| Settled fraction per borough | **Estimated** |
| Gastronomy intensity per borough | **Estimated** |
| The rectangles each borough is swept as | **Estimated**, and deliberately loose |

The last two are guesses with a documented rationale, and they are the ones a
probe pass replaces with measurements. The 25% contingency in the planning
figure exists for them.

## Layout

| Module | Role |
|---|---|
| `berlin/districts.py` | The twelve boroughs: area, population, settled share, gastronomy intensity |
| `berlin/pricing.py` | Google's Places SKUs, free monthly allowances, the trial credit |
| `berlin/cost.py` | The measured cost law, per-borough plans, refresh economics |
| `berlin/sweep.py` | The type filter and the commands to run |
| `berlin/cli.py` | `plan`, `cost`, `commands`, `skus`, `types`, `facts` |
| `tools/calibrate.py` | The offline replay that measured the law |

## Tests

```bash
pip install -e ".[dev]"
pytest
```

No network calls. The interesting ones assert the model reproduces the
measurement it came from (`calls_for(1110, 207)` against the 2,390 calls
actually observed), that cost follows the geometric mean rather than either
term, that census mode is priced off a measured ratio rather than by extending
a curve that does not reach there, and that the borough table still sums to
Berlin's published area and population.

## Terms of service

This is Google Places content. Place IDs may be cached indefinitely; names,
ratings, addresses and phone numbers generally may not be kept beyond 30 days,
and the content must not be used to build a competing service or a standalone
database sold on. If this is going to drive commercial outreach at scale, read
[the Maps Platform terms](https://cloud.google.com/maps-platform/terms)
sections 3.2.3 and 3.2.4 and get it reviewed. Neither this repo nor
allRestaurants makes that call for you.
