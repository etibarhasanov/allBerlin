"""Berlin's outline, and the arithmetic for laying a grid over it.

A city boundary is not a rectangle and pretending otherwise is expensive.  The
bounding box of Berlin is 1,710 km2 against a city of 892 km2, so half of every
call made against the box lands in Brandenburg.  This polygon is a 38-vertex
approximation of the administrative border -- coarse enough to write down,
close enough that the grid it produces is the city rather than the box.

It comes out at 955 km2 against Berlin's official 891.8, about 7% generous.
The excess sits along the border, which is the cheapest ground there is: an
empty cell costs one call and never splits.
"""

from __future__ import annotations

import math
from typing import List, Sequence, Tuple

LatLng = Tuple[float, float]

# Clockwise from the northern tip at Frohnau.  Named vertices are the extreme
# points of the city, which is what a reader can check.
BERLIN_OUTLINE: List[LatLng] = [
    (52.6755, 13.2860),   # Frohnau -- northernmost point of Berlin
    (52.6450, 13.3100), (52.6350, 13.3800), (52.6280, 13.4200),
    (52.6350, 13.4700),
    (52.6650, 13.5050),   # Buch
    (52.6400, 13.5250), (52.6100, 13.5350), (52.5900, 13.5750),
    (52.5650, 13.5950),   # Ahrensfelde
    (52.5400, 13.6350), (52.5150, 13.6250), (52.4900, 13.6900),
    (52.4550, 13.7100),
    (52.4250, 13.7612),   # Muggelheim -- easternmost point
    (52.4000, 13.7200), (52.3850, 13.6800),
    (52.3700, 13.6300),   # Schmockwitz
    (52.3800, 13.5900), (52.3950, 13.5600), (52.4000, 13.5200),
    (52.3800, 13.4900), (52.3900, 13.4500),
    (52.3382, 13.4100),   # Lichtenrade -- southernmost point
    (52.3900, 13.3900), (52.4000, 13.3400), (52.3950, 13.2800),
    (52.3900, 13.2000), (52.4100, 13.1600),
    (52.4300, 13.1300),   # Kladow
    (52.4700, 13.1150), (52.5000, 13.1300),
    (52.5300, 13.0884),   # Staaken -- westernmost point
    (52.5600, 13.1200), (52.5800, 13.1700), (52.6000, 13.2100),
    (52.6300, 13.2400), (52.6500, 13.2700),
]

# The official figure, for the tests to hold the polygon to.
BERLIN_AREA_KM2 = 891.8

METRES_PER_DEGREE_LAT = 111_320.0


def metres_per_degree_lng(lat: float) -> float:
    return max(METRES_PER_DEGREE_LAT * math.cos(math.radians(lat)), 1.0)


def polygon_area_km2(polygon: Sequence[LatLng]) -> float:
    """Shoelace area, on a local equirectangular projection."""
    if len(polygon) < 3:
        raise ValueError("a polygon needs at least three vertices")
    lat0 = sum(p[0] for p in polygon) / len(polygon)
    kx = metres_per_degree_lng(lat0) / 1000.0
    ky = METRES_PER_DEGREE_LAT / 1000.0
    pts = [(lng * kx, lat * ky) for lat, lng in polygon]
    total = 0.0
    for i in range(len(pts)):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % len(pts)]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


def contains(polygon: Sequence[LatLng], lat: float, lng: float) -> bool:
    """Ray casting, in degrees. Good enough at a city's scale."""
    inside = False
    n = len(polygon)
    for i in range(n):
        y1, x1 = polygon[i]
        y2, x2 = polygon[(i + 1) % n]
        if (y1 > lat) != (y2 > lat):
            x_at = x1 + (lat - y1) * (x2 - x1) / (y2 - y1)
            if x_at > lng:
                inside = not inside
    return inside


def bbox(polygon: Sequence[LatLng]) -> Tuple[float, float, float, float]:
    """south, west, north, east."""
    return (min(p[0] for p in polygon), min(p[1] for p in polygon),
            max(p[0] for p in polygon), max(p[1] for p in polygon))


def berlin_area_km2() -> float:
    return polygon_area_km2(BERLIN_OUTLINE)


def berlin_bbox_area_km2() -> float:
    south, west, north, east = bbox(BERLIN_OUTLINE)
    return polygon_area_km2([(south, west), (south, east), (north, east), (north, west)])
