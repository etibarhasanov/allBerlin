"""Command line interface: plan, price, execute and score a Berlin census."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import List, Optional

from . import __version__, hexgrid
from .census import (BERLIN_PRIVATE_ENTITIES, BERLIN_REGISTERED_COMPANIES,
                     DEFAULT_QPS, DEFAULT_SCORING_RESOLUTION, MAPPABLE_SHARE,
                     enrichment_cost, entities_in, modelled_counts,
                     modelled_population, plan_census, settled_density,
                     total_entities)
from .districts import DISTRICTS
from .entities import (ANCHOR_CATEGORIES, CATEGORIES, PRIVATE_CATEGORIES,
                       by_key, types_argument)
from .geometry import BERLIN_AREA_KM2, berlin_area_km2, berlin_bbox_area_km2
from .hexgrid import resolution, resolution_table
from .pricing import (DETAILS_ENTERPRISE, DETAILS_SKUS, FREE_TRIAL_USD,
                      NEARBY_IDS, NEARBY_PRO, NEARBY_SKUS)
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
    plan = plan_census(res=args.res)
    r = resolution(plan.res)
    print(f"\n  Counting every private entity in Berlin, on an H3 res-{plan.res} grid")
    print(f"  ({r.cell_area_km2:.3f} km2 a cell, {r.edge_m:.0f} m across the "
          f"corner, {plan.cells:,} cells)\n")
    head = (f"  {'category':<22}{'entities':>10}{'saturated':>11}"
            f"{'calls':>10}{'hours':>7}")
    print(head)
    print("  " + "-" * (len(head) - 2))
    for p in sorted(plan.passes, key=lambda p: -p.calls):
        print(f"  {p.category.key:<22}{p.entities:>10,.0f}{p.saturated_cells:>11,}"
              f"{p.calls:>10,.0f}{p.hours:>7.1f}")
    print("  " + "-" * (head.__len__() - 2))
    print(f"  {'TOTAL':<22}{plan.entities:>10,.0f}{plan.saturated_cells:>11,}"
          f"{plan.calls:>10,.0f}{plan.hours:>7.1f}")
    b = plan.billing()
    print(f"\n  SKU  : {plan.sku.name}")
    print(f"  COST : ${b['usd']:,.2f}")
    print(f"  TIME : {plan.hours:.1f} hours at {DEFAULT_QPS:.0f} calls/second\n")
    print("  The whole census is free because IDs-Only carries no monthly cap.")
    print("  What it costs is wall-clock, so the number to manage is calls, and")
    print("  the lever on calls is the resolution.\n")
    for alt in (8, 9, 10):
        if alt == plan.res:
            continue
        other = plan_census(res=alt)
        print(f"    res {alt}: {other.cells:>7,} cells, {other.calls:>9,.0f} calls, "
              f"{other.hours:>5.1f} h")
    print()
    return 0


def cmd_cost(args) -> int:
    plan = plan_census(res=args.res)
    print(f"\n  Berlin private-entity census, H3 res {plan.res}\n")
    print(f"  entities (modelled) : {plan.entities:,.0f}")
    print(f"  cells               : {plan.cells:,}")
    print(f"  API calls           : {plan.calls:,.0f}")
    print(f"  wall clock          : {plan.hours:.1f} hours at "
          f"{DEFAULT_QPS:.0f} calls/second")
    print(f"\n  COST: ${plan.billing()['usd']:,.2f}   "
          f"({NEARBY_IDS.name}, free with no monthly cap)\n")
    print(f"  Against a ${FREE_TRIAL_USD:.0f} free trial credit, this spends "
          f"none of it.\n")

    print("  What you would pay if you wanted more than a count:\n")
    e = enrichment_cost(plan.entities, plan.calls)
    print(f"    the same sweep at Pro (name, address, location, types)")
    print(f"      {plan.calls:,.0f} calls x ${NEARBY_PRO.usd_per_1000:.2f}/1,000 "
          f"= ${e['sweep_at_pro_usd']:,.2f}")
    print(f"    {e['details_sku']} afterwards on every id, one place per call")
    print(f"      {plan.entities:,.0f} calls = ${e['details_per_entity_usd']:,.2f}")
    print()
    print("  Note which way round that is. For a review-bearing dataset the")
    print("  free SKU is a trap, because an id with no review count forces a")
    print("  census and then $20/1,000 of Place Details to find out what you")
    print("  collected. For a count there is nothing to find out afterwards:")
    print("  the count IS the product, and the trap never springs.\n")
    print("  The middle path, if some cells need detail: census everything for")
    print(f"  free, then re-sweep only the cells you care about at Pro. A "
          f"hundred\n  cells is ${100 * NEARBY_PRO.usd_per_call:,.2f}.\n")
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
    from .runner import CountStore, HexCensus

    api_key = args.api_key or os.environ.get("GOOGLE_MAPS_API_KEY")
    if not api_key:
        print("error: no API key. Set GOOGLE_MAPS_API_KEY or pass --api-key.",
              file=sys.stderr)
        return 1

    res = args.res or DEFAULT_SCORING_RESOLUTION
    categories = ([by_key(k) for k in args.category] if args.category
                  else list(CATEGORIES))
    cells = hexgrid.berlin_cells(res)
    if args.limit:
        cells = cells[:args.limit]

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(message)s",
                        datefmt="%H:%M:%S")
    store = CountStore(args.db)
    # tier="ids" is the whole economic argument: the free SKU, no monthly cap.
    client = PlacesClient(api_key=api_key, tier="ids", qps=args.qps,
                          max_requests=args.max_requests)
    try:
        for category in categories:
            census = HexCensus(client, store, category, res, workers=args.workers)
            stats = census.run(cells)
            print(f"  {category.key:<22}{stats.cells_done:>7,} cells "
                  f"{stats.calls:>8,} calls {stats.entities:>8,} places "
                  f"{stats.inexact_cells:>5,} inexact")
    finally:
        total = store.unique_entities()
        store.close()
        print(f"\n  {total:,} distinct places, {client.request_count:,} calls, "
              f"stored in {args.db}\n")
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
    print("\n  Nearby Search -- one call, up to 20 places\n")
    _sku_table(NEARBY_SKUS)
    print("\n  Place Details -- one call, one place you already have an id for\n")
    _sku_table(DETAILS_SKUS)
    print("\n  A request bills at the highest SKU any field in its mask belongs")
    print("  to. Asking for one review count on an otherwise-Pro call prices")
    print("  the whole call as Enterprise; there is no partial billing.")
    print("\n  Which is why this product asks for nothing but the id.\n")
    return 0


def _sku_table(skus) -> None:
    head = f"  {'SKU':<40}{'$/1,000':>10}{'free/month':>12}  what it buys"
    print(head)
    print("  " + "-" * (len(head) - 2))
    for s in skus:
        free = "unlimited" if s.usd_per_1000 == 0 else f"{s.free_calls_per_month:,}"
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
    p.add_argument("--category", action="append",
                   help="Category key; repeatable. Default: all of them.")
    p.add_argument("--db", default="data/berlin_census.db")
    p.add_argument("--api-key", help="Overrides GOOGLE_MAPS_API_KEY.")
    p.add_argument("--qps", type=float, default=DEFAULT_QPS)
    p.add_argument("--workers", type=int, default=5)
    p.add_argument("--limit", type=int, default=None,
                   help="Only the first N cells -- for a first look.")
    p.add_argument("--max-requests", type=int, default=None,
                   help="Hard call cap. The run stops cleanly and resumes.")
    p.set_defaults(func=cmd_run)

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
