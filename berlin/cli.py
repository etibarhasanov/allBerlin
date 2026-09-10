"""Command line interface: plan, price, execute and score a Berlin census."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import List, Optional

from . import __version__, hexgrid
from .census import (ALL_POI_FACTOR, BERLIN_PRIVATE_ENTITIES,
                     BERLIN_REGISTERED_COMPANIES, DEFAULT_QPS,
                     DEFAULT_SCORING_RESOLUTION, MAPPABLE_SHARE,
                     enrichment_cost, entities_in, modelled_counts,
                     modelled_population, plan_census, settled_density,
                     total_entities, two_stage_cost)
from .districts import DISTRICTS
from .entities import (ANCHOR_CATEGORIES, CATEGORIES, PRIVATE_CATEGORIES,
                       by_key, types_argument)
from .geometry import BERLIN_AREA_KM2, berlin_area_km2, berlin_bbox_area_km2
from .hexgrid import resolution, resolution_table
from .pricing import (DETAILS_ENTERPRISE, DETAILS_SKUS, FREE_TRIAL_USD,
                      NEARBY_PRO, NEARBY_SKUS, TEXT_SKUS)
from .scoring import PROFILES, build_features, profile, score_cells, top_cells


def cmd_grid(args) -> int:
    print("\n  H3 resolutions over Berlin. The query circle circumscribes the")
    print("  cell, so it covers 1.21x the cell's ground and neighbours overlap.\n")
    head = (f"  {'res':>4}{'cell km2':>10}{'edge m':>9}{'query r':>9}"
            f"{'cap bites at':>15}{'cells':>10}  what it is")
    print(head)
    print("  " + "-" * (len(head) - 2))
    notes = {
        7: "the whole inner city in one cell",
        8: "a district view",
        9: "a five-minute walk -- the scoring default",
        10: "a block, for siting one door",
        11: "finer than Google's own placement accuracy",
    }
    for r in resolution_table(7, 11):
        cells = len(hexgrid.berlin_cells(r.res)) if r.res <= 10 else 0
        shown = f"{cells:,}" if cells else "-"
        print(f"  {r.res:>4}{r.cell_area_km2:>10.5f}{r.edge_m:>9.0f}"
              f"{r.query_radius_m:>9.0f}{r.saturating_density:>11,.0f}/km2"
              f"{shown:>10}  {notes.get(r.res, '')}")
    print(f"\n  A k-ring is 3k(k+1)+1 cells: {hexgrid.ring_size(1)} at k=1, "
          f"{hexgrid.ring_size(2)} at k=2, {hexgrid.ring_size(3)} at k=3.")
    print("  Six neighbours, one distance -- which is the reason for hexagons.\n")
    return 0


def cmd_categories(args) -> int:
    print(f"\n  {len(CATEGORIES)} categories over "
          f"{len({t for c in CATEGORIES for t in c.types})} Google place types.\n")
    head = f"  {'category':<22}{'types':>6}{'share':>7}{'kind':>9}  purpose"
    print(head)
    print("  " + "-" * (len(head) - 2))
    for c in CATEGORIES:
        kind = "private" if c.private else "anchor"
        print(f"  {c.key:<22}{len(c.types):>6}{c.share:>7.2f}{kind:>9}  "
              f"{c.note.splitlines()[0] if c.note else ''}")
    if args.category:
        c = by_key(args.category)
        print(f"\n  {c.label} ({c.key}):\n")
        print(f"  {types_argument(c)}\n")
    else:
        print("\n  Pass --category KEY for one category's full type list.\n")
    return 0


def cmd_census(args) -> int:
    plan = plan_census(res=args.res, months=args.months)
    r = resolution(plan.res)
    p = plan.passes[0]
    print(f"\n  Every place Google indexes in Berlin, with coordinates and types,")
    print(f"  on an H3 res-{plan.res} grid ({r.cell_area_km2:.3f} km2 a cell, "
          f"{r.edge_m:.0f} m to the corner, {plan.cells:,} cells)\n")
    print(f"  one untyped Nearby Search per cell, quartered where it saturates")
    print(f"    cells                : {p.cells:,}")
    print(f"    cells over the cap   : {p.saturated_cells:,}")
    print(f"    calls                : {p.calls:,.0f}")
    print(f"    private entities     : {p.entities:,.0f}  "
          f"(x{ALL_POI_FACTOR} of everything, parks and bus stops included)")
    print(f"    wall clock           : {plan.hours:.1f} h at {DEFAULT_QPS:.0f}/s")
    b = plan.billing()
    print(f"\n  SKU  : {plan.sku.name}  (${plan.sku.usd_per_1000:.2f}/1,000, "
          f"{plan.sku.free_calls_per_month:,} free a month)")
    print(f"  COST : ${b['usd']:,.2f}   (list ${b['usd_before_free_tier']:,.2f}, "
          f"over {plan.months} month(s))\n")
    print("  The resolution is a genuine trade-off here, not a monotone:")
    for alt in (8, 9, 10):
        other = plan_census(res=alt, months=args.months)
        mark = "  <-" if alt == plan.res else ""
        print(f"    res {alt}: {other.cells:>7,} cells, {other.calls:>8,.0f} calls, "
              f"{other.saturated_cells:>6,} split, ${other.billing()['usd']:>9,.2f}{mark}")
    print("\n  Coarser cells save the empty-cell floor and pay for it in splitting;")
    print("  finer cells do the reverse. Res 9 sits at the bottom of the curve.\n")
    return 0


def cmd_cost(args) -> int:
    plan = plan_census(res=args.res, months=args.months)
    b = plan.billing()
    print(f"\n  Berlin: every entity with coordinates and a category, H3 res {plan.res}\n")
    print(f"  ROUTE A  {plan.sku.name}, one untyped pass")
    print(f"    {plan.calls:,.0f} calls, {plan.hours:.1f} h, "
          f"{plan.entities:,.0f} private entities")
    print(f"    ${b['usd']:,.2f} after {b['free_calls']:,.0f} free calls   "
          f"(list ${b['usd_before_free_tier']:,.2f})")
    two = plan_census(res=plan.res, months=2).billing()
    if plan.months == 1:
        print(f"    ${two['usd']:,.2f} if the run straddles two months")
    print()

    t = two_stage_cost(plan.entities, res=plan.res, months=plan.months)
    print(f"  ROUTE B  free discovery, then coordinates and types per id")
    print(f"    1. {t['discovery_sku']}: {t['discovery_calls']:,.0f} calls, "
          f"{t['discovery_hours']:.1f} h, $0.00")
    print(f"    2. {t['details_sku']}: {t['details_calls']:,.0f} calls, "
          f"${t['details_usd']:,.2f} after {t['details_free_calls']:,.0f} free")
    print(f"    ${t['total_usd']:,.2f} in {plan.months} month(s); $0.00 spread over "
          f"{t['months_to_be_free']} months at 10,000 free a month")
    print(f"    CAVEAT: Text Search is a search, not an enumeration. Run it and")
    print(f"    Route A over the same 50 cells and compare the id sets before")
    print(f"    trusting it for a census. Unverified, this saving is not real.")
    print()

    trial = FREE_TRIAL_USD
    print(f"  Against the ${trial:.0f} free trial credit:")
    for label, usd in (("Route A, one month", b["usd"]), ("Route A, two months", two["usd"]),
                       ("Route B, one month", t["total_usd"])):
        verdict = "inside" if usd <= trial else f"${usd - trial:,.0f} over"
        print(f"    {label:<22} ${usd:>8,.2f}   {verdict}")
    print()

    e = enrichment_cost(plan.entities, plan.calls)
    print("  If you later want ratings and review counts as well (Enterprise):")
    print(f"    re-run Route A at Enterprise     +${e['resweep_at_enterprise_extra_usd']:,.2f} on top")
    print(f"    Place Details Enterprise per id  ${e['details_enterprise_usd']:,.2f}")
    print()
    print("  There is no free Nearby Search tier. Text Search and Place")
    print("  Details have one; Nearby Search bills at Pro even for ids alone.")
    print("  An earlier version of this tool said otherwise and priced the whole")
    print("  census at $0.00. That figure was wrong.\n")
    return 0


def cmd_score(args) -> int:
    prof = profile(args.profile)
    res = args.res or DEFAULT_SCORING_RESOLUTION
    print(f"\n  Profile: {prof.key} -- {prof.question}")
    print(f"  Grid   : H3 res {res}, {len(hexgrid.berlin_cells(res)):,} cells")
    print("\n  *** MODELLED, NOT MEASURED. These scores come from the density")
    print("      model in census.py, not from any API call. Run `allberlin run`")
    print("      to replace them with counts. ***\n")
    counts = modelled_counts(res)
    features = build_features(counts, rings=(1, 2),
                              population=modelled_population(res))
    scores = score_cells(features, prof)
    print(f"  rewards : " + ", ".join(f"{k} x{v}" for k, v in prof.weights.items()))
    if prof.penalties:
        print(f"  punishes: " + ", ".join(f"{k} x{v}" for k, v in prof.penalties.items()))
    print()
    head = f"  {'#':>3}  {'cell':<17}{'lat,lng':>19}{'score':>8}{'entities':>10}"
    print(head)
    print("  " + "-" * (len(head) - 2))
    by_cell = {f.cell: f for f in features}
    for i, (cell, score) in enumerate(top_cells(scores, args.top), 1):
        lat, lng = hexgrid.cell_center(cell)
        print(f"  {i:>3}  {cell:<17}{lat:>10.4f},{lng:<8.4f}{score:>8.3f}"
              f"{by_cell[cell].total:>10.0f}")
    print()
    return 0


def cmd_profiles(args) -> int:
    print("\n  There is no single good location. A site is good for something.\n")
    for p in PROFILES.values():
        print(f"  {p.key:<14}{p.question}")
        print(f"  {'':<14}rewards  " + ", ".join(f"{k} x{v}" for k, v in p.weights.items()))
        if p.penalties:
            print(f"  {'':<14}punishes " + ", ".join(
                f"{k} x{v}" for k, v in p.penalties.items()))
        print()
    return 0


def cmd_run(args) -> int:
    """Actually make the calls. This is the only command that spends anything."""
    try:
        from allrestaurants.places import PlacesClient
    except ImportError:
        print("error: allberlin run needs the allRestaurants package:\n"
              "  pip install -e ../allRestaurants", file=sys.stderr)
        return 1
    from .runner import FIELD_MASK, CountStore, HexCensus

    api_key = args.api_key or os.environ.get("GOOGLE_MAPS_API_KEY")
    if not api_key:
        print("error: no API key. Set GOOGLE_MAPS_API_KEY or pass --api-key.",
              file=sys.stderr)
        return 1

    res = args.res or DEFAULT_SCORING_RESOLUTION
    cells = hexgrid.berlin_cells(res)
    if args.limit:
        cells = cells[:args.limit]
    plan = plan_census(res=res)
    per_cell = plan.calls / plan.cells
    est_calls = per_cell * len(cells)
    print(f"\n  {len(cells):,} cells at res {res}: about {est_calls:,.0f} calls, "
          f"${est_calls * NEARBY_PRO.usd_per_call:,.2f} at list price.")
    if args.max_requests:
        print(f"  Hard cap: {args.max_requests:,} calls "
              f"(${args.max_requests * NEARBY_PRO.usd_per_call:,.2f}).")
    print()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(message)s",
                        datefmt="%H:%M:%S")
    os.makedirs(os.path.dirname(args.db) or ".", exist_ok=True)
    store = CountStore(args.db)
    # Pro tier: id, name, coordinates, types, address. Nothing dearer -- one
    # rating in the mask would re-price every call to Enterprise.
    client = PlacesClient(api_key=api_key, tier="standard", qps=args.qps,
                          max_requests=args.max_requests)
    client.field_mask = FIELD_MASK
    try:
        census = HexCensus(client, store, res, workers=args.workers)
        stats = census.run(cells)
        print(f"\n  cells done {stats.cells_done:,}  skipped {stats.cells_skipped:,}  "
              f"failed {stats.cells_failed:,}")
        print(f"  calls {stats.calls:,}  splits {stats.splits:,}  "
              f"clipped {stats.clipped:,}  deepest split {stats.max_depth}")
    finally:
        total = store.unique_places()
        store.close()
        print(f"  {total:,} distinct places with coordinates, "
              f"{client.request_count:,} calls, in {args.db}\n")
    return 0


def cmd_export(args) -> int:
    """Write every distinct place -- id, name, lat, lng, category -- to CSV."""
    import csv

    from .runner import CountStore

    if not os.path.exists(args.db):
        print(f"error: no census at {args.db}. Run `allberlin run` first.",
              file=sys.stderr)
        return 1
    store = CountStore(args.db)
    rows = store.iter_places()
    store.close()
    with open(args.out, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["place_id", "name", "lat", "lng", "primary_type", "types",
                    "category", "address", "business_status", "h3_r9"])
        for r in rows:
            w.writerow(list(r) + [hexgrid.h3.latlng_to_cell(r[2], r[3], 9)])
    print(f"  wrote {len(rows):,} places to {args.out}")
    return 0


def cmd_facts(args) -> int:
    print(f"\n  Berlin, in the numbers this model uses:\n")
    print(f"    area (official)        : {BERLIN_AREA_KM2:,.1f} km2")
    print(f"    outline polygon        : {berlin_area_km2():,.1f} km2 "
          f"({berlin_area_km2() / BERLIN_AREA_KM2 - 1:+.0%})")
    print(f"    bounding box           : {berlin_bbox_area_km2():,.1f} km2 "
          f"-- why the grid is not a box")
    print(f"    registered companies   : {BERLIN_REGISTERED_COMPANIES:,}")
    print(f"    of them mappable       : {MAPPABLE_SHARE:.0%} = "
          f"{BERLIN_PRIVATE_ENTITIES:,}")
    print(f"    modelled entities      : {total_entities():,.0f}\n")
    head = f"  {'borough':<28}{'entities':>10}{'per km2 built up':>19}"
    print(head)
    print("  " + "-" * (len(head) - 2))
    for d in sorted(DISTRICTS, key=lambda d: -settled_density(d)):
        print(f"  {d.name:<28}{entities_in(d):>10,.0f}{settled_density(d):>19,.0f}")
    print()
    return 0


def cmd_skus(args) -> int:
    print("\n  Nearby Search -- one call, up to 20 places. No IDs-Only tier.\n")
    _sku_table(NEARBY_SKUS)
    print("\n  Text Search -- a query in a rectangle, up to 60 places over 3 pages\n")
    _sku_table(TEXT_SKUS)
    print("\n  Place Details -- one call, one place you already have an id for\n")
    _sku_table(DETAILS_SKUS)
    print("\n  A request bills at the highest SKU any field in its mask belongs")
    print("  to. Asking for one review count on an otherwise-Pro call prices")
    print("  the whole call as Enterprise; there is no partial billing.")
    print("\n  Pro is the floor for Nearby Search, and Pro already carries the two")
    print("  fields a location product needs beyond the id: coordinates and types.\n")
    return 0


def _sku_table(skus) -> None:
    head = f"  {'SKU':<40}{'$/1,000':>10}{'free/month':>12}  what it buys"
    print(head)
    print("  " + "-" * (len(head) - 2))
    for s in skus:
        free = "no cap" if s.usd_per_1000 == 0 else f"{s.free_calls_per_month:,}"
        print(f"  {s.name:<40}{s.usd_per_1000:>10.2f}{free:>12}  {s.buys}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="allberlin",
        description="Count every private entity in Berlin on a hex grid, "
                    "and score locations from the result.")
    parser.add_argument("--version", action="version",
                        version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def with_res(p):
        p.add_argument("--res", type=int, default=None,
                       help=f"H3 resolution. Default {DEFAULT_SCORING_RESOLUTION} "
                            f"(~200 m cells, a five-minute walk).")
        p.add_argument("--months", type=int, default=1,
                       help="Calendar months the run spans; the free allowance "
                            "applies once per month and does not roll over.")
        return p

    p = sub.add_parser("grid", help="H3 resolutions over Berlin.")
    p.set_defaults(func=cmd_grid)

    p = sub.add_parser("categories", help="The private-entity taxonomy.")
    p.add_argument("--category", help="Show one category's full type list.")
    p.set_defaults(func=cmd_categories)

    p = with_res(sub.add_parser("census", help="Calls and hours for a full census."))
    p.set_defaults(func=cmd_census)

    p = with_res(sub.add_parser("cost", help="What it costs, and what detail costs."))
    p.set_defaults(func=cmd_cost)

    p = with_res(sub.add_parser("score", help="Score Berlin under one profile."))
    p.add_argument("--profile", default="footfall", choices=sorted(PROFILES))
    p.add_argument("--top", type=int, default=10)
    p.set_defaults(func=cmd_score)

    p = sub.add_parser("profiles", help="The scoring profiles, and their weights.")
    p.set_defaults(func=cmd_profiles)

    p = with_res(sub.add_parser("run", help="Make the calls. Needs an API key."))
    p.add_argument("--db", default="data/berlin_census.db")
    p.add_argument("--api-key", help="Overrides GOOGLE_MAPS_API_KEY.")
    p.add_argument("--qps", type=float, default=DEFAULT_QPS)
    p.add_argument("--workers", type=int, default=5)
    p.add_argument("--limit", type=int, default=None,
                   help="Only the first N cells -- for a first look.")
    p.add_argument("--max-requests", type=int, default=None,
                   help="Hard call cap. The run stops cleanly and resumes.")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("export", help="Every place with coordinates and category, as CSV.")
    p.add_argument("--db", default="data/berlin_census.db")
    p.add_argument("--out", default="exports/berlin_places.csv")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("facts", help="Berlin in the numbers this model uses.")
    p.set_defaults(func=cmd_facts)

    p = sub.add_parser("skus", help="Google's Places SKUs and free allowances.")
    p.set_defaults(func=cmd_skus)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
