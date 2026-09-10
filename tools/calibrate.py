#!/usr/bin/env python3
"""Measure what a sweep costs, instead of assuming it.

The allRestaurants estimate assumes every saturated circle splits into four.
That assumption has already been wrong once by a factor of 1.7, in the
expensive direction, when it priced Tallinn's districts at 286 calls against an
actual 171.  It cannot be right in general: splitting is driven by how
restaurants clump together, and a grid does not know where the clumps are.

So this measures.  It replays the real Sweeper -- the real splitting rule, the
real 20-result cap, the real review bar -- over the 1,110 real Tallinn
coordinates in ``exports/tallinn_restaurants.csv``, with the point set
thickened two-, four- and eightfold to stand in for a denser city than Tallinn.
Thickened copies are scattered around their original, so the clumping survives.

No network, no API key, no money.  Run it against a checkout of
etibarhasanov/allRestaurants:

    python3 tools/calibrate.py --allrestaurants ../allRestaurants

The output is the constant in berlin/cost.py.
"""

from __future__ import annotations

import argparse
import csv
import math
import os
import random
import sys
import tempfile
from typing import Dict, List, Sequence, Tuple

Place = Tuple[str, float, float, int]


def load_places(csv_path: str) -> List[Place]:
    out = []
    with open(csv_path) as fh:
        for row in csv.DictReader(fh):
            if row["latitude"] and row["longitude"] and row["user_rating_count"]:
                out.append((row["place_id"], float(row["latitude"]),
                            float(row["longitude"]), int(row["user_rating_count"])))
    return out


def thicken(places: Sequence[Place], factor: int, geo, seed: int = 11) -> List[Place]:
    """Multiply the point set ``factor``-fold, keeping its clustering.

    Copies land on a 80m gaussian around their original, so a dense district
    stays dense and an empty one stays empty.  That matters: an evenly spread
    city would be far cheaper to sweep than any real one, and calibrating on
    one would understate every figure downstream.
    """
    if factor == 1:
        return list(places)
    rnd = random.Random(seed)
    out: List[Place] = []
    for pid, lat, lng, reviews in places:
        out.append((pid, lat, lng, reviews))
        for i in range(factor - 1):
            dlat = rnd.gauss(0, 80) / geo.METRES_PER_DEGREE_LAT
            dlng = rnd.gauss(0, 80) / geo.metres_per_degree_lng(lat)
            out.append((f"{pid}#{i}", lat + dlat, lng + dlng,
                        max(25, reviews // (i + 2))))
    return out


class _Index:
    """Bucketed lookup, so an 8,880-point replay finishes in seconds."""

    CELL_DEG = 0.005  # ~550m

    def __init__(self, places: Sequence[Place], geo):
        self.geo = geo
        self.buckets: Dict[Tuple[int, int], List[Place]] = {}
        for p in places:
            self.buckets.setdefault(self._key(p[1], p[2]), []).append(p)

    def _key(self, lat: float, lng: float) -> Tuple[int, int]:
        return (int(lat / self.CELL_DEG), int(lng / self.CELL_DEG))

    def near(self, lat: float, lng: float, radius_m: float):
        d_lat = radius_m / self.geo.METRES_PER_DEGREE_LAT
        d_lng = radius_m / self.geo.metres_per_degree_lng(lat)
        for i in range(int((lat - d_lat) / self.CELL_DEG),
                       int((lat + d_lat) / self.CELL_DEG) + 1):
            for j in range(int((lng - d_lng) / self.CELL_DEG),
                           int((lng + d_lng) / self.CELL_DEG) + 1):
                for p in self.buckets.get((i, j), ()):
                    yield p


class FakePlaces:
    """Google's Nearby Search, minus the network and the bill.

    Returns the 20 highest-reviewed places inside the circle, which is what
    POPULARITY ranking does and what the sweep's stopping rule reads.
    """

    def __init__(self, places: Sequence[Place], geo):
        self.geo = geo
        self.index = _Index(places, geo)
        self.request_count = 0

    def search_nearby(self, circle, **kwargs):
        self.request_count += 1
        inside = [p for p in self.index.near(circle.lat, circle.lng, circle.radius_m)
                  if self.geo.haversine_m(circle.lat, circle.lng, p[1], p[2])
                  <= circle.radius_m]
        inside.sort(key=lambda p: -p[3])
        return [
            {"id": p[0], "displayName": {"text": p[0]},
             "location": {"latitude": p[1], "longitude": p[2]},
             "rating": 4.0, "userRatingCount": p[3],
             "primaryType": "restaurant", "types": ["restaurant"]}
            for p in inside[:20]
        ]


def replay(cell_radius_m: float, bbox, universe, target_ids, modules) -> Dict[str, float]:
    geo, Sweeper, Store = modules
    south, west, north, east = bbox
    circles = geo.cover_bbox(south, west, north, east, cell_radius_m)
    client = FakePlaces(universe, geo)
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)
    store = Store(path)
    try:
        stats = Sweeper(client, store, workers=1, min_reviews=25,
                        rank_preference="POPULARITY", min_radius_m=40.0,
                        max_depth=7, restaurants_only=False,
                        progress_every=0).run(circles)
        found = {r[0] for r in store.conn.execute("SELECT place_id FROM restaurants")}
    finally:
        store.close()
        os.unlink(path)
    return {"level0": len(circles), "calls": client.request_count,
            "splits": stats.cells_split,
            "recall": len(found & target_ids) / len(target_ids)}


def bbox_of(places: Sequence[Place], geo):
    lats = [p[1] for p in places]
    lngs = [p[2] for p in places]
    bbox = (min(lats), min(lngs), max(lats), max(lngs))
    area = ((bbox[2] - bbox[0]) * geo.METRES_PER_DEGREE_LAT / 1000) * \
           ((bbox[3] - bbox[1]) * geo.metres_per_degree_lng(sum(lats) / len(lats)) / 1000)
    return bbox, area


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--allrestaurants", default="../allRestaurants",
                    help="Path to a checkout of etibarhasanov/allRestaurants.")
    ap.add_argument("--factors", default="1,2,4,8",
                    help="Density multipliers to measure.")
    ap.add_argument("--radii", default="150,200,250,300,400,500",
                    help="Starting circle radii to try, in metres.")
    args = ap.parse_args(argv)

    root = os.path.abspath(args.allrestaurants)
    sys.path.insert(0, os.path.join(root, "src"))
    try:
        from allrestaurants import geo
        from allrestaurants.scrape import Sweeper
        from allrestaurants.store import Store
    except ImportError as exc:
        print(f"error: cannot import allrestaurants from {root}: {exc}", file=sys.stderr)
        print("  pass --allrestaurants /path/to/allRestaurants", file=sys.stderr)
        return 1
    modules = (geo, Sweeper, Store)

    csv_path = os.path.join(root, "exports", "tallinn_restaurants.csv")
    if not os.path.exists(csv_path):
        print(f"error: no Tallinn dataset at {csv_path}", file=sys.stderr)
        return 1

    base = load_places(csv_path)
    bbox, area = bbox_of(base, geo)
    print(f"Tallinn: {len(base)} places over a {area:.0f} km2 bbox "
          f"({len(base) / area:.1f}/km2), review bar 25+\n")

    header = (f"{'x':>3}{'places':>8}{'/km2':>7}{'cell':>6}{'calls':>8}"
              f"{'splits':>8}{'recall':>8}{'calls/km2':>11}{'constant':>10}")
    print(header)
    print("-" * len(header))

    constants = []
    for factor in [int(f) for f in args.factors.split(",")]:
        universe = thicken(base, factor, geo)
        target_ids = {p[0] for p in universe}
        best = None
        for radius in [float(r) for r in args.radii.split(",")]:
            result = replay(radius, bbox, universe, target_ids, modules)
            constant = result["calls"] / math.sqrt(len(universe) * area)
            print(f"{factor:>3}{len(universe):>8}{len(universe) / area:>7.1f}"
                  f"{radius:>6.0f}{result['calls']:>8}{result['splits']:>8}"
                  f"{result['recall'] * 100:>7.1f}%{result['calls'] / area:>11.2f}"
                  f"{constant:>10.2f}")
            if best is None or result["calls"] < best[0]:
                best = (result["calls"], radius, constant, result["recall"])
        constants.append(best[2])
        print(f"    -> cheapest at {best[1]:.0f}m: {best[0]} calls, "
              f"recall {best[3] * 100:.1f}%, constant {best[2]:.2f}\n")

    mean = sum(constants) / len(constants)
    spread = max(abs(c - mean) for c in constants) / mean
    print(f"calls ~= {mean:.2f} * sqrt(places * area_km2)")
    print(f"  per-density constants: {', '.join(f'{c:.2f}' for c in constants)}")
    print(f"  spread about the mean: {spread:.1%}")
    print("\nThe geometric mean is the finding. Cost follows neither area alone")
    print("(an empty square kilometre costs one call) nor the place count alone")
    print("(calls per place FALL as density rises) but the two together.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
