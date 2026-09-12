# allBerlin

**A map of every business in Berlin — where it is, what kind it is, and how
many stand near any point — as the foundation for a location-scoring
product.**

This document is written for two readers at once. The first half is for
anyone: what this is, what it produces, what it costs, and how to decide
where to spend. The second half is for whoever runs it. You can stop at the
line between them and have the whole picture.

---

## Part 1 — For everyone

### What this is

Google Maps knows about roughly 120,000 businesses in Berlin — cafés, shops,
hairdressers, dentists, law offices, gyms, hotels. This project collects them
from Google, records **where each one is** and **what kind of business it is**,
and lays them out on a grid of small hexagons across the city, each about 200
metres wide — a two-minute walk.

From that, for any spot in Berlin, you can answer questions like:

- How many businesses are within a short walk of here?
- What kinds? Mostly food? Mostly offices? A real mix?
- Is this corner busier than that one — and by how much?
- Where would a new café have customers but not too many rivals?
- Where do a lot of people live with very little around them?

That last group of questions is what a **location intelligence** product
sells. This is the data layer underneath it.

### What you get

A database (and a spreadsheet, if you prefer) with one line per business:

| field | example | what it is |
|---|---|---|
| Place ID | `ChIJN1t_tDeuEmsRUsoyG83frY4` | Google's permanent identifier for that business |
| Name | Bäckerei Siebert | |
| Coordinates | 52.5448, 13.4071 | latitude and longitude — where it is on the map |
| Google's type | `bakery` | the single best label Google gives it |
| All types | bakery, food store, store… | every label Google gives it |
| **Category** | **Food and drink** | our grouping of Google's ~180 labels into 12 kinds |
| Address | Schönfließer Str. 12, 10439 Berlin | |
| Status | open / temporarily closed / closed | |
| Grid cell | `891f1d48b17ffff` | which hexagon it sits in |

And for every hexagon in the city, the **density**: how many businesses are
within a two-minute walk of its centre, and how many of each category.

The twelve categories: **Food and drink · Retail · Personal services** (hair,
beauty, laundry) **· Professional and financial** (banks, lawyers, agencies)
**· Health · Leisure and culture · Sport and fitness · Lodging · Automotive
· Trades and logistics · Education and childcare · Transport nodes.** The last
two are not businesses but are kept because a school or a station changes what
a location is worth.

### What it costs

Google charges for this data per request, and one request returns at most
twenty places. Covering the whole city means about **31,000 requests**, which
takes **under an hour** to run and costs:

| | |
|---|---|
| Whole of Berlin, everything above, in one go | **about $840** |
| The same, if the run straddles the end of a month | **about $680** — Google's free allowance applies twice |
| A cheaper two-step route (explained below) | **about $549**, or **$0 over twelve months** — *if it checks out* |

Google also gives new accounts a **$300 trial credit**, which comes off any of
these.

**Why isn't it free?** Google's map service has a few free tiers, and it is
easy to assume the one used here has one too. It does not. An earlier version
of this project made exactly that assumption and said the whole thing would
cost nothing. It was wrong, and the correction is recorded in this document
rather than quietly removed, because the mistake is easy to repeat.

### Cost follows density, not size

This is the single most useful thing to understand before deciding what to
collect.

A request returns at most twenty places. In a quiet suburb, one request per
hexagon finds everything. In the centre, one hexagon can hold a hundred
businesses, so it has to be asked about repeatedly in smaller pieces, and
every piece is another request. **A busy area costs many times more than a
quiet one of the same size.**

Here is the same 2 km circle drawn around different points — the same number
of hexagons every time:

| centre of the circle | businesses inside | cost to collect |
|---|---|---|
| Alexanderplatz (Mitte) | ~11,400 | **$121** |
| Kottbusser Tor (Kreuzberg) | ~9,500 | **$99** |
| Zoo (Charlottenburg) | ~5,600 | **$52** |
| Spandau old town | ~800 | **$4** |
| Marzahn | ~600 | **$4** |

Thirty times the price for the same-sized circle. Mitte alone is over a third
of the whole-city bill on a twentieth of its area.

### You do not have to do the whole city

Because cost follows density, the sensible way to work is to **pick the areas
you care about**, see what they would cost, and collect only those. The tool
does this: you name some points and a radius around each, and it tells you
how many businesses to expect, how dense they are, and the bill.

Two things make this cheaper than it looks:

- **Google gives 5,000 free requests every month** on this tier — about $160
  worth. That covers a lot of Berlin. All of Spandau, Marzahn-Hellersdorf,
  Lichtenberg and Reinickendorf together fit inside it. So do a 2 km circle
  around Kottbusser Tor plus a 3 km one around Charlottenburg.
- **Areas that are already collected are never paid for twice.** Add more
  next month, on next month's free allowance.

Whole boroughs, for reference:

| borough | businesses (est.) | cost |
|---|---|---|
| Mitte | 36,000 | $371 |
| Friedrichshain-Kreuzberg | 15,000 | $152 |
| Charlottenburg-Wilmersdorf | 12,600 | $95 |
| Treptow-Köpenick | 5,800 | $63 |
| Pankow | 10,400 | $57 |
| Neukölln | 8,800 | $55 |
| Tempelhof-Schöneberg | 8,100 | $54 |
| Spandau | 4,200 | $40 |
| Steglitz-Zehlendorf | 6,500 | $40 |
| Reinickendorf | 5,000 | $35 |
| Marzahn-Hellersdorf | 3,800 | $23 |
| Lichtenberg | 3,600 | $15 |
| **All of Berlin** | **~120,000** | **$1,000 list, $840 after the free allowance** |

### What "density" means here

Two numbers are reported for any area, and they answer different questions.

**Businesses per square kilometre** is the one to *compare* places by. It
does not depend on how big a circle you drew. Alexanderplatz is around 800
per km²; Spandau around 60.

**Businesses per hexagon** — the count within a two-minute walk of a point —
is what the scoring uses, and it is also the number that decides cost. Above
twenty, a hexagon has to be asked about in pieces. Alexanderplatz averages
about 107 per hexagon; Spandau about 8.

### The cheaper route, and its catch

Google has a *different* search service — a text search, the kind you type
"bakery near Alexanderplatz" into — that will return just the identifiers of
matching places for free. Identifiers alone are useless, but for each one you
can then ask Google for the coordinates and type at **$5 per thousand, with
the first 10,000 each month free**. For 120,000 businesses that is about $549
in one month, or nothing at all if spread over a year.

The catch: a text search is a *search*. It ranks results by how well they
match the words you typed. It is not guaranteed to hand over everything in an
area the way the main method is. So before relying on it, the two methods
have to be run over the same fifty hexagons and their results compared. That
check costs about $2. If the results match, the cheap route is real. If they
don't, it never was. The tool prints this warning next to the figure every
time.

### Why hexagons

Because every hexagon touches six neighbours, all the same distance away. A
square touches four along its edges and four at its corners, and the corner
ones are 41% further off — so "what is near here" on a square grid always
has to fudge which neighbours count. A location score is mostly a statement
about a neighbourhood, and a grid that distorts neighbourhoods distorts the
product.

The hexagons follow a public standard called **H3**, so a cell's identifier
means the same thing to anyone else who uses it — census data, property
data, transport data can all be joined on it. Cells come in sizes:

| size | width | cells in Berlin | what it is for |
|---|---|---|---|
| coarse | ~1 km | 1,454 | a district-level view |
| **default** | **~400 m across, 200 m to a corner** | **10,155** | **a five-minute walk — neighbourhood scoring** |
| fine | ~150 m | 71,114 | a single block, for siting one door |

The default is also the cheapest to collect: coarse cells cost more because
every one of them has to be broken into pieces; fine cells cost more because
there are so many empty ones to ask about. And since every business is stored
with its coordinates, the results can be re-laid onto any of these sizes
afterwards for nothing.

### Is the data yours to keep?

Partly. Google lets you keep the **identifiers forever**. The rest — names,
coordinates, types, addresses — is Google's content and generally may not be
stored for more than about 30 days. So a dataset with coordinates in it needs
refreshing monthly, and the refresh is the cheap operation ($5 per thousand,
10,000 free a month). If the data is going to be sold as a product rather
than used internally, Google's terms (sections 3.2.3 and 3.2.4 of the
[Maps Platform terms](https://cloud.google.com/maps-platform/terms)) need a
proper reading first. This project does not make that call for you.

### What exists today

- **The tool** — complete and tested. It plans, prices, collects, stores and
  scores.
- **A modelled preview** — a page showing what the output looks like, built
  from an estimate of where Berlin's businesses are (borough statistics and a
  distance-from-centre curve). It is deliberately smooth and marked as
  modelled on every screen. It is a demonstration of the shape, **not
  data**.
- **No collected data yet.** Collection needs a Google Maps key on an account
  with billing enabled, a machine that can reach Google, and — for the whole
  city — about $840 or an hour of runtime, whichever you find more expensive.

---

## Part 2 — For whoever runs it

### Setup

```bash
git clone <this repo> && cd allBerlin
pip install -e . -e ../allRestaurants      # the second is the Places client
export GOOGLE_MAPS_API_KEY=...             # Places API (New) enabled, billing on
```

Restrict the key to **Places API (New)**. The request's field mask is pinned to
the Pro tier in `runner.py` — one rating in it would re-price every call to
Enterprise — so it is deliberately not a command-line flag.

### The commands

```bash
allberlin grid                 # the resolutions, and what each is for
allberlin categories           # the taxonomy; --category retail for its type list
allberlin census               # whole-city calls, hours, cost, by resolution
allberlin cost                 # both routes against the $300 trial credit
allberlin areas --at ...       # price chosen areas; --cells-out writes the cell list
allberlin run                  # make the calls (whole city, or --cells-file)
allberlin density --at ...     # measured density per area, from the database
allberlin export               # every place with coordinates and category, as CSV
allberlin score --profile ...  # score the (modelled) surface under a profile
```

A first look, ~150 calls, about $5:

```bash
allberlin run --limit 50
```

Chosen areas:

```bash
allberlin areas \
  --at "Alexanderplatz:52.5219,13.4132:2" \
  --at "Kottbusser Tor:52.4990,13.4180:2" \
  --at "Spandau:52.5370,13.2000:2" \
  --cells-out cells.txt
allberlin run --cells-file cells.txt
allberlin density --at "Alexanderplatz:52.5219,13.4132:2" --at ...
```

The whole city, capped so a surprise cannot cost more than you decided:

```bash
allberlin run --res 9 --max-requests 35000
allberlin export --out exports/berlin_places.csv
```

Cells already done are skipped on a re-run; interrupting is safe.

### What the run does

For each hexagon, one **Nearby Search** request with no type filter, asking
for the circle that circumscribes the cell (radius = the hexagon's edge, 205 m
at the default resolution). Google returns the nearest twenty places with
coordinates, name, types and address.

If twenty came back, more are hiding. The circle is quartered — four circles
at (±r/2, ±r/2) with radius r/√2 — and each quarter asked again, recursively,
up to eight levels (about 15 m). The four quarters reach *outside* the parent
circle, so every result is kept only if its own coordinates fall inside the
cell's circle. That filter is what makes the count exact, and it is only
possible because the Pro tier returns coordinates. (The earlier IDs-only
design could not filter and had to split the type list instead; that
machinery is gone.)

Neighbouring circles overlap by about a fifth, so a place near a seam is found
from two cells and stored under both. A city total is `SELECT COUNT(DISTINCT
place_id)` and exact.

### What lands in the database

`data/berlin_census.db`, SQLite.

**`places`** — one row per (cell, place): `cell, place_id, name, lat, lng,
primary_type, types, category, address, business_status`.

**`cell_census`** — the resume log: `cell, resolution, n, calls, max_depth`.

`allberlin export` writes one row per distinct place with its res-9 cell
alongside. To load somewhere else, the store is one class
(`berlin/runner.py: CountStore`).

### How the estimates were made

Nothing in the cost figures is a guess about Google's behaviour; the
behaviour was measured. What *is* estimated is where Berlin's businesses are,
and that is what the first fifty cells of a real run will correct.

| | source |
|---|---|
| Hex geometry, cell counts, ring sizes | exact, computed |
| Prices, free allowances, which endpoints have a free tier | Google's pricing pages, September 2026 |
| Cost of breaking a saturated cell (4.4 calls per multiple of the cap) | **measured** on the allRestaurants fixture |
| Over-reach of quartering without coordinates (21%) | **measured** on a known clump |
| Berlin registered companies (190,000) | published |
| Share of them that are on the map (63%), non-business places per business (×1.35) | estimated |
| Business intensity per borough; falloff from the centre; smoothing | estimated |

One cross-check holds without being arranged for: this model reaches Berlin's
eateries through company counts and gets 16,758; the independent review-based
model in `berlin/cost.py` reaches them through Tallinn's measured rate and
gets 10,649 with 25+ reviews. Different routes, no shared inputs, and the
second sits sensibly inside the first.

### From places to a score

Three things stand between a count and a score. Each is a decision, and each
is visible in `berlin/scoring.py` rather than buried in a weight.

**Neighbourhood.** Every feature has a catchment form, summed over the
k-ring — 7 cells at k=1, 19 at k=2.

**Comparability.** Raw counts are badly skewed; Mitte would dominate any
average-based normalisation. Features are converted to **percentile ranks**
across the city: 0.9 means denser than 90% of Berlin. Ties share a rank,
because most cells have zero of most categories.

**Purpose.** No single "good location". Named profiles, each with weights
*and penalties* — a profile that cannot say "too much of this is bad" cannot
express competition.

| profile | question |
|---|---|
| `footfall` | Where are people already passing? |
| `retail_site` | Where would a new shop trade well? *(penalises existing retail)* |
| `food_site` | Where would a new café trade well? *(penalises existing food)* |
| `underserved` | Where do residents live with the least around them? |
| `office` | Where is the weekday, daytime economy? |

### Layout

| module | role |
|---|---|
| `berlin/geometry.py` | Berlin's outline — the bounding box is 1.9× the city |
| `berlin/hexgrid.py` | H3 grid, cell → query circle, k-rings, resolutions |
| `berlin/entities.py` | 179 Google types in 12 categories |
| `berlin/pricing.py` | The SKUs, and which endpoints have a free tier |
| `berlin/census.py` | Calls, hours, both routes, the modelled surface |
| `berlin/areas.py` | Named circles: cells, cost, measured density |
| `berlin/runner.py` | The collection: one untyped pass, clipped quartering, resume |
| `berlin/scoring.py` | Features, percentile ranks, profiles |
| `berlin/cost.py` | The review-bearing variant, priced separately |

### Tests

```bash
pip install -e ".[dev]" && pytest
```

153 tests, no network. The ones that carry weight: a saturated cell is
quartered to the **exact** count at 25, 40, 90 and 200 places; results from
outside the cell are clipped; every stored place has coordinates and a
category; ids deduplicate across cell seams; `pricing.py` has no free Nearby
Search tier; an area outside Berlin is refused; overlapping areas are billed
once; `underserved` does not peak in the centre.

---

## Glossary

**Place ID** — Google's permanent identifier for one place. The one thing
Google lets you keep indefinitely.

**Nearby Search** — the Google request used here: "everything within this
circle". Returns at most twenty, nearest first.

**Pro tier** — the cheapest level at which Nearby Search can be asked for
anything. Includes coordinates, types, name and address. $32 per thousand
requests; 5,000 free a month.

**Enterprise tier** — the next level up, which adds ratings, review counts,
phone numbers and opening hours. Not collected here; one such field re-prices
every request.

**Text Search / Place Details** — two other Google services, both with a free
identifier-only level. The cheaper two-step route uses them.

**H3 / cell / resolution** — the hexagon standard, one hexagon, and how big
the hexagons are. Resolution 9 is the default: ~400 m across.

**Saturation / splitting** — a cell that returned the maximum twenty and must
be asked about in smaller pieces. The main driver of cost.

**Density** — businesses per km² (to compare areas) or per cell (what scoring
sees and what drives cost).

**Percentile rank** — where a cell stands against all others in the city, 0
to 1. Used instead of raw counts so no single feature dominates.

**Profile** — a named set of weights and penalties that turns features into
one score for one purpose.
