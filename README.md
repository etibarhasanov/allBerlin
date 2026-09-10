# allBerlin

Every place in Berlin with its **coordinates** and its **category**, indexed
on a hexagonal grid, as the base layer for a location intelligence scoring
product.

Not a directory — a **surface** with the points still in it. For each of
10,155 cells you get what stands within a two-minute walk, what kind of thing
each one is, and exactly where; from that you can ask the only question a
location product is really asked: *is this a good place to put this thing,
and compared to what?*

```bash
git clone <this repo> && cd allBerlin
pip install -e . -e ../allRestaurants

allberlin grid            # the hex resolutions, and what each one is for
allberlin census          # calls, hours and cost for the whole city
allberlin cost            # both routes, against the free trial
allberlin score --profile food_site
allberlin run             # make the calls (needs a Google Maps key)
allberlin export          # place_id, name, lat, lng, category -> CSV
```

---

## The answer

**About 31,000 API calls, under an hour, and $840 — or $680 if the run
straddles two calendar months.** That is one pass of Nearby Search Pro over
the city, and it returns every place with its coordinates, its Google types,
its name and its address.

| | cells | calls | hours | after free tier |
|---|---|---|---|---|
| res 8 — a district view | 1,454 | 40,173 | 1.1 | $1,126 |
| **res 9 — a five-minute walk** | **10,155** | **31,242** | **0.9** | **$840** |
| res 10 — a block | 71,114 | 71,825 | 2.0 | $2,138 |

Res 9 is the bottom of a real curve, not a default: coarser cells save the
empty-cell floor and pay for it in splitting, finer cells do the reverse.

There is a cheaper route to the same two fields, and it is conditional:

| | calls | cost |
|---|---|---|
| **Route A** — Nearby Search Pro, one untyped pass | 31,242 | **$840** ($680 over two months) |
| **Route B** — Text Search IDs-Only (free) to discover, then Place Details Essentials for coordinates and types | 123,000 + 119,700 | **$549** in one month, **$0** spread over twelve |

Route B's discovery step is a *search*, ranked against a query string — not
an enumeration of a circle the way Nearby Search is. Nothing guarantees it
finds everything. Before trusting it for a census, run both routes over the
same fifty cells and compare the id sets. If they match, Route B is the price;
if they do not, the saving was never real. `allberlin cost` says this every
time it prints the figure.

Neither route fits inside the **$300 free trial credit** on its own. Route A
over two months is $380 over; Route B in one month is $249 over, and free with
patience.

### A correction

An earlier version of this repository priced the census at **$0.00**, on the
strength of a "Nearby Search Essentials (IDs Only)" SKU. **There is no such
SKU.** Text Search and Place Details each have a free IDs-Only tier; Nearby
Search does not, and a Nearby Search request that asks for nothing but
`places.id` is billed at Pro, $32 per 1,000. The `allrestaurants` price table
carried the same error and has been corrected in the same change.

It turns out to change less than it looks. Pro is the tier that carries
`location` and `types` — precisely the two fields this product needs beyond
the id — so the correction and the request for coordinates and categories are
one and the same change. Once every result says what and where it is, two
things happen:

- **Category comes back with each place**, so the twelve typed passes of the
  free design collapse into **one untyped pass**: a single request per cell,
  no `includedTypes`, returns the nearest twenty of everything and each one
  names its type. About a fifth of the calls.
- **Coordinates make geometric splitting exact.** A saturated cell is
  quartered and every result kept only if it lies inside the cell's own
  circle. The IDs-only design could not filter on coordinates it did not have,
  and had to split the type list instead; that machinery is gone.

## Why hexagons

Every cell has six neighbours at one distance. A square grid has four edge
neighbours and four corner ones 1.41× further, and every "what is around
here" question then has to pick a lie to tell about that. A location score is
almost entirely a statement about a *neighbourhood*, so a grid that distorts
neighbourhoods distorts the product. A k-ring is 3k(k+1)+1 cells — 7, 19, 37 —
and that is the whole catchment arithmetic. [H3](https://h3geo.org) is a global
standard index, so a cell id here means the same thing in whatever the scores
are joined against later.

| res | cell | across | what it is |
|---|---|---|---|
| 8 | 0.74 km² | 531 m | a district view |
| **9** | **0.105 km²** | **201 m** | **a five-minute walk — the default** |
| 10 | 0.015 km² | 76 m | a block, for siting one door |

The grid decides the *query* granularity; with coordinates on every place,
you can re-index the results to any resolution afterwards for nothing.
`allberlin export` writes the res-9 cell of each place alongside its
coordinates for exactly that reason.

## What one place looks like

```
place_id        ChIJ...
name            Bäckerei Siebert
lat, lng        52.5448, 13.4071
primary_type    bakery
types           bakery,food_store,store,food,point_of_interest,establishment
category        food_drink
address         Schönfließer Str. 12, 10439 Berlin
business_status OPERATIONAL
h3_r9           891f1d48b17ffff
```

Category is read off Google's own type list through the taxonomy in
`berlin/entities.py` — 179 types in 12 categories, the first match winning
and the primary type winning over that. A place typed as nothing in the
taxonomy (a park, a monument) is kept as `other`, because it still occupied
one of the twenty slots and still says something about the block.

## From places to a score

Three things stand between a count and a score, and each is a decision that
should be visible rather than buried in a weighting.

**Neighbourhood.** Every feature has a catchment form summed over the k-ring.

**Comparability.** Raw counts are badly skewed — a mean-and-standard-deviation
normalisation would be dominated by the top hundred cells in Mitte. Features
become **percentile ranks** across the city: 0.9 means denser than 90% of
Berlin. Ties share a rank, because most cells hold zero of any given category
and breaking those ties would make the bottom half of every score noise
presented as signal.

**Purpose.** There is no single good location, so there is no default score —
there are profiles, each a set of weights **and penalties**. A profile that
cannot say "too much of this is bad" cannot express competition, and
competition is most of what site selection is.

| profile | question |
|---|---|
| `footfall` | Where are people already passing? |
| `retail_site` | Where would a new shop trade well? *(penalises existing retail)* |
| `food_site` | Where would a new cafe trade well? *(penalises existing food)* |
| `underserved` | Where do residents live with the least around them? |
| `office` | Where is the weekday, daytime economy? |

`allberlin score` runs the pipeline against a **modelled** surface so the
output can be seen before a key is involved, and says so loudly. The surface
is smooth by construction — borough commercial intensity, a distance-to-centre
gradient, a hex-ring smooth to remove the borough edges — and deliberately not
roughened with plausible-looking noise, because a surface that looked like
data would invite being used as data.

## What is measured and what is modelled

| | source |
|---|---|
| H3 geometry, cell counts, ring sizes | **Exact** — computed |
| SKU prices, free allowances, which endpoints have an IDs-Only tier | Google's pricing pages, September 2026 |
| Quartering cost (4.4 calls per multiple of the cap) | **Measured** on the allRestaurants fixture |
| Quadtree over-reach without coordinates (21%) | **Measured** against a known clump |
| Berlin registered companies (190,000) | Published |
| Mappable share (63%), all-POI factor (1.35) | **Estimated** |
| Commercial intensity per borough, density gradient | **Estimated** |

Everything after `allberlin run` is measured. Everything before it exists to
size the run and to let the pipeline be tested without one. One cross-check
holds unarranged: this model reaches Berlin's eateries through
registered-company counts and gets 16,758; the independent review-bar model
in `berlin/cost.py` reaches them through Tallinn's measured gastronomy rate
and gets 10,649 with 25+ reviews. Different routes, no shared inputs.

## Running it

```bash
export GOOGLE_MAPS_API_KEY=...

allberlin run --limit 50                 # ~150 calls, ~$5: proves the key
allberlin run --res 9 --max-requests 35000
allberlin export --out exports/berlin_places.csv
```

Restrict the key to **Places API (New)**. The field mask is fixed at the Pro
tier in `runner.py` — one rating in it would re-price every call to
Enterprise — so it is not exposed as a flag. Cells already done are skipped on
a re-run; at $32 per 1,000 that is money as well as hours.

Results land in `data/berlin_census.db`: `places` with one row per (cell, place)
carrying coordinates, types and category; `cell_census` as the resume log. A
place near a seam is found from two cells and stored under both; the city
total is a `DISTINCT` over ids and exact.

## Layout

| Module | Role |
|---|---|
| `berlin/geometry.py` | Berlin's outline — the bounding box is 1.9× the city |
| `berlin/hexgrid.py` | H3 grid, cell → query circle, k-rings, resolutions |
| `berlin/entities.py` | 179 Google types in 12 categories |
| `berlin/pricing.py` | The SKUs, and which endpoints have a free tier |
| `berlin/census.py` | Calls, hours, both routes, the modelled surface |
| `berlin/runner.py` | The census: one untyped pass, clipped quartering, resume |
| `berlin/scoring.py` | Features, percentile ranks, profiles |
| `berlin/cost.py` | The review-bearing variant, priced separately |

## Tests

```bash
pip install -e ".[dev]" && pytest
```

144 tests, no network. The ones that carry weight: that a saturated cell is
quartered to the **exact** count at 25, 40, 90 and 200 places; that results
a child circle returns from outside the cell are clipped; that every stored
place has coordinates and a category; that ids deduplicate across the seam
between cells where naive addition inflates; that `pricing.py` has **no**
`NEARBY_IDS`; and that `underserved` does not peak in the middle of Berlin.

## Terms of service

Place ids may be cached indefinitely. Coordinates, names, addresses and types
are content, and content generally may not be kept beyond 30 days — so a
dataset with coordinates in it needs refreshing monthly (Place Details
Essentials at $5 per 1,000, 10,000 free a month, is the cheap way), and if it
is going to be sold as a product rather than used internally, read
[the Maps Platform terms](https://cloud.google.com/maps-platform/terms)
sections 3.2.3 and 3.2.4 and get it reviewed.
