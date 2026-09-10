"""Command line interface: plan a Berlin sweep and price it."""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from . import __version__
from .cost import (CONTINGENCY, Plan, build_plan, ids_only_is_a_false_economy,
                   refresh_cost, share_above_bar)
from .districts import (BERLIN_AREA_KM2, DISTRICTS, total_area_km2,
                        total_expected_places, total_population,
                        total_settled_km2)
from .pricing import (BY_TIER, DETAILS_ENTERPRISE, DETAILS_SKUS,
                      FREE_TRIAL_DAYS, FREE_TRIAL_USD, NEARBY_SKUS, bill)
from .sweep import TYPES, script, types_argument

TIERS = ["ids", "standard", "ratings", "full"]


def _plan_from(args) -> Plan:
    return build_plan(
        sku=BY_TIER[args.tier],
        min_reviews=args.min_reviews,
        settled_only=not args.whole_area,
        months=args.months,
    )


def cmd_plan(args) -> int:
    plan = _plan_from(args)
    ground = "settled ground only" if not args.whole_area else "every square km"
    print(f"\nBerlin sweep plan -- {ground}, places with {plan.min_reviews}+ reviews\n")
    head = (f"{'borough':<27}{'swept':>7}{'live':>7}{'places':>8}{'/km2':>7}"
            f"{'cell m':>8}{'calls':>8}{'empty':>7}{'per pl':>8}")
    print(head)
    print("-" * len(head))
    for p in plan.districts:
        print(f"{p.district.name:<27}{p.swept_km2:>7.1f}{p.area_km2:>7.1f}"
              f"{p.places:>8.0f}{p.places / p.area_km2:>7.1f}"
              f"{p.cell_radius_m:>8.0f}{p.calls:>8.0f}{p.overhead_calls:>7.0f}"
              f"{p.calls_per_place:>8.2f}")
    print("-" * len(head))
    print(f"{'total':<27}{plan.swept_km2:>7.1f}{plan.area_km2:>7.1f}"
          f"{plan.places:>8.0f}{plan.places / plan.area_km2:>7.1f}{'':>8}"
          f"{plan.productive_calls:>8.0f}{plan.overhead_calls:>7.0f}"
          f"{plan.calls / plan.places:>8.2f}")
    print(f"\n  {plan.calls:.0f} calls in total, of which {plan.overhead_calls:.0f}"
          f" cover the {plan.swept_km2 - plan.area_km2:.0f} km2 of lake, forest and"
          f"\n  borough fringe that a rectangle cannot avoid taking in.")
    print(f"  With {CONTINGENCY:.0%} contingency: {plan.planning_calls:.0f} calls.")
    print("  Sweep the cheap boroughs first; `allberlin commands` orders them that way.\n")
    return 0


def cmd_cost(args) -> int:
    plan = _plan_from(args)
    sku = plan.sku
    measured = plan.billing(contingency=False)
    planning = plan.billing(contingency=True)

    print(f"\nBerlin, every eatery with {plan.min_reviews}+ Google reviews")
    print(f"  ground swept        : {plan.swept_km2:.0f} km2 of Berlin's "
          f"{BERLIN_AREA_KM2:.0f} km2, of which {plan.area_km2:.0f} km2 is built up")
    print(f"  places expected     : {plan.places:,.0f}")
    print(f"  SKU                 : {sku.name} (${sku.usd_per_1000:.2f}/1,000)")
    print(f"  buys you            : {sku.buys}")
    print()
    print(f"  API calls (model)   : {measured['calls']:,.0f}")
    print(f"  API calls (planning): {planning['calls']:,.0f}  "
          f"(+{CONTINGENCY:.0%} contingency)")
    print(f"  free this month     : {sku.free_calls_per_month:,} calls/month"
          f" x {plan.months} month(s) = {planning['free_calls']:,.0f}")
    print()
    print(f"  list price          : ${planning['usd_before_free_tier']:,.2f}")
    print(f"  after the free tier : ${planning['usd']:,.2f}"
          f"   (model, no contingency: ${measured['usd']:,.2f})")
    print()

    trial = FREE_TRIAL_USD
    worst, best = planning["usd"], measured["usd"]
    if worst <= trial:
        verdict = (f"YES -- even with contingency this fits inside the "
                   f"${trial:.0f} free trial credit.")
    elif best <= trial:
        verdict = (f"BORDERLINE -- the model fits inside the ${trial:.0f} trial "
                   f"credit (${best:,.0f}), the contingency does not "
                   f"(${worst:,.0f}). Probe first, and see the levers below.")
    else:
        verdict = (f"NO -- ${best:,.0f} at best against a ${trial:.0f} credit, "
                   f"so ${best - trial:,.0f}-${worst - trial:,.0f} is real money. "
                   f"The levers below close that gap.")
    print(f"  Free trial ({FREE_TRIAL_DAYS} days, ${trial:.0f} credit): {verdict}")
    print()

    print("  Levers, cheapest first:")
    for bar in (50, 100, 200):
        if bar <= plan.min_reviews:
            continue
        alt = build_plan(sku=sku, min_reviews=bar,
                         settled_only=not args.whole_area, months=plan.months)
        saved = measured["usd"] - alt.billing(contingency=False)["usd"]
        print(f"    --min-reviews {bar:<4} {alt.places:>7,.0f} places, "
              f"{alt.calls:>7,.0f} calls, ${alt.billing(contingency=False)['usd']:>7,.2f}"
              f"   (saves ${saved:,.2f})")
    two = build_plan(sku=sku, min_reviews=plan.min_reviews,
                     settled_only=not args.whole_area, months=2)
    print(f"    run over 2 months  free tier applies twice, "
          f"${two.billing(contingency=False)['usd']:,.2f}"
          f"   (saves ${measured['usd'] - two.billing(contingency=False)['usd']:,.2f})")
    if not args.whole_area:
        wide = build_plan(sku=sku, min_reviews=plan.min_reviews,
                          settled_only=False, months=plan.months)
        extra = wide.billing(contingency=False)["usd"] - measured["usd"]
        print(f"    (skipping the settled-ground clip would ADD ${extra:,.2f}: "
              f"{wide.calls - measured['calls']:,.0f} calls over lakes and forest)")
    print()

    print("  Keeping it current -- Google's terms allow caching place IDs")
    print("  indefinitely but the content on them for about 30 days:")
    resweep = plan.billing(contingency=False)["usd"]
    details = refresh_cost(plan.places, DETAILS_ENTERPRISE)
    print(f"    re-sweep monthly            ${resweep:,.2f}/month")
    print(f"    Place Details on known IDs  ${details['usd']:,.2f}/month "
          f"({details['calls']:,.0f} calls at ${DETAILS_ENTERPRISE.usd_per_1000:.2f}/1,000)")
    cheaper = "Place Details" if details["usd"] < resweep else "a re-sweep"
    print(f"    -> {cheaper} is the cheaper refresh at this size.")
    print()
    return 0


def cmd_skus(args) -> int:
    print("\nNearby Search -- one call, up to 20 places\n")
    _sku_table(NEARBY_SKUS)
    print("\nPlace Details -- one call, one place you already have the ID for\n")
    _sku_table(DETAILS_SKUS)
    print("\n  A request bills at the highest SKU any field in its mask belongs")
    print("  to. One review count on an otherwise-Pro call prices the whole")
    print("  call as Enterprise; there is no partial billing.\n")

    est = ids_only_is_a_false_economy(total_expected_places(),
                                      total_expected_places() * 3.48)
    print("  The free IDs-Only SKU does not make this free:")
    print(f"    discovery would cost nothing, and return "
          f"{est['places_discovered']:,.0f} bare IDs")
    print(f"    with no review count to filter on, so details on all of them: "
          f"${est['details_usd']:,.2f}")
    print(f"    ${est['usd_per_place_via_details']:.4f}/place via Place Details "
          f"against ${est['usd_per_place_via_nearby']:.4f}/place via Nearby "
          f"Search, which returns 20 at a time.\n")
    return 0


def _sku_table(skus) -> None:
    head = f"  {'SKU':<40}{'$/1,000':>10}{'free/month':>12}  what it buys"
    print(head)
    print("  " + "-" * (len(head) - 2))
    for s in skus:
        free = "unlimited" if s.usd_per_1000 == 0 else f"{s.free_calls_per_month:,}"
        print(f"  {s.name:<40}{s.usd_per_1000:>10.2f}{free:>12}  {s.buys}")


def cmd_commands(args) -> int:
    plan = _plan_from(args)
    text = script(plan, args.tier)
    if args.out:
        with open(args.out, "w") as fh:
            fh.write(text + "\n")
        print(f"wrote {args.out}")
    else:
        print(text)
    return 0


def cmd_types(args) -> int:
    if args.bare:
        # Meant for `TYPES=$(allberlin types --bare)`.
        print(types_argument())
        return 0
    print(f"\n{len(TYPES)} types:\n")
    print(types_argument())
    print("\n  Google returns a place only when the requested type appears in")
    print("  that place's own type list. Asking for 'restaurant' alone misses")
    print("  every cafe, bakery, pub and bar -- 22 of 25 misses in Tallinn.\n")
    return 0


def cmd_facts(args) -> int:
    print(f"\n  boroughs         : {len(DISTRICTS)}")
    print(f"  area             : {total_area_km2():.1f} km2")
    print(f"  settled (modelled): {total_settled_km2():.1f} km2 "
          f"({total_settled_km2() / total_area_km2():.0%})")
    print(f"  population       : {total_population():,}")
    print(f"  eateries 25+ rev : {total_expected_places():,.0f} (modelled)\n")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="allberlin",
        description="Plan and price a Google Places sweep of every eatery in Berlin.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def shared(p):
        p.add_argument("--min-reviews", type=int, default=25,
                       help="Review bar. The biggest cost lever there is. Default 25.")
        p.add_argument("--tier", choices=TIERS, default="ratings",
                       help="Field tier, which picks the SKU. Default 'ratings' "
                            "-- the one that carries rating and review count.")
        p.add_argument("--months", type=int, default=1,
                       help="Calendar months to spread the run over; the free "
                            "monthly allowance applies once per month.")
        p.add_argument("--whole-area", action="store_true",
                       help="Tile every square km, lakes and forest included, "
                            "instead of the settled share.")
        return p

    p = shared(sub.add_parser("plan", help="Per-borough call counts."))
    p.set_defaults(func=cmd_plan)

    p = shared(sub.add_parser("cost", help="What the sweep costs, and whether "
                                           "the free trial covers it."))
    p.set_defaults(func=cmd_cost)

    p = shared(sub.add_parser("commands", help="Emit the allrestaurants commands."))
    p.add_argument("--out", help="Write to a file instead of stdout.")
    p.set_defaults(func=cmd_commands)

    p = sub.add_parser("skus", help="Google's Places SKUs and free allowances.")
    p.set_defaults(func=cmd_skus)

    p = sub.add_parser("types", help="The type filter to sweep Berlin with.")
    p.add_argument("--bare", action="store_true",
                   help="Print just the comma-separated list, for $(...) use.")
    p.set_defaults(func=cmd_types)

    p = sub.add_parser("facts", help="Berlin in the numbers this model uses.")
    p.set_defaults(func=cmd_facts)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
