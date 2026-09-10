"""Berlin's twelve boroughs, and what each one costs to sweep.

The sweep cost turns on two numbers per borough: how much ground has to be
tiled with search circles, and how many eateries sit on it.  Neither is the
headline figure people quote.

*Ground* is not the borough's area.  Treptow-Koepenick is Berlin's largest
borough at 168 km2 and most of it is the Mueggelsee, the Koepenicker Forst and
the Wuhlheide -- tiling water and pine costs exactly as much per call as tiling
Kreuzberg and returns nothing.  ``settled_fraction`` is the share worth
searching at all.

*Eateries* is not the population.  Mitte feeds three million tourists a year on
a resident population smaller than Pankow's.  ``gastro_intensity`` is how many
eateries per resident a borough carries against the city average, so Mitte's
2.6 and Marzahn-Hellersdorf's 0.5 are doing real work in the estimate.

Areas and populations are the official Amt fuer Statistik Berlin-Brandenburg
figures.  The two modelled factors are estimates -- documented here precisely
so they can be argued with, and so ``allberlin probe`` can replace them with
measurements for about a hundred API calls before any real money is committed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Tuple

# Eateries with 25+ Google reviews per 1,000 residents, measured in Tallinn:
# 1,110 places in exports/tallinn_restaurants.csv against 461,000 residents.
# This is the one constant the whole place-count estimate rests on, and it is
# measured rather than assumed -- see CALIBRATION.md.
TALLINN_PLACES_PER_1000_RESIDENTS = 1110 / 461.0


def tile_area_km2(tile: Tuple[float, float, float, float]) -> float:
    """Ground area of a south, west, north, east rectangle."""
    south, west, north, east = tile
    mid = math.radians((south + north) / 2)
    return ((north - south) * 111.320) * ((east - west) * 111.320 * math.cos(mid))


@dataclass(frozen=True)
class District:
    """One Berlin borough (Bezirk)."""

    name: str
    area_km2: float
    population: int
    # Share of the borough that is built up rather than forest, lake, field or
    # airfield.  Only this part is worth covering with search circles.
    settled_fraction: float
    # Eateries per resident against the city average.  Above 1 for the tourist
    # and nightlife boroughs, below 1 for the outer housing estates.
    gastro_intensity: float
    # Somewhere central, for --center runs and for probing density.
    center: Tuple[float, float]
    # The rectangles actually swept, each south, west, north, east.  Not the
    # borough's bounding box: a single rectangle around Treptow-Koepenick is
    # 446 km2 for a 168 km2 borough, most of it the Mueggelsee.  Awkward shapes
    # get two or three rectangles around their built-up parts instead, which
    # takes the ground swept across Berlin from 1,925 km2 down to about 645.
    tiles: Tuple[Tuple[float, float, float, float], ...]

    @property
    def settled_km2(self) -> float:
        """The ground actually worth tiling."""
        return self.area_km2 * self.settled_fraction

    @property
    def swept_km2(self) -> float:
        """The ground the tiles actually cover, settled or not."""
        return sum(tile_area_km2(t) for t in self.tiles)

    @property
    def bbox(self) -> Tuple[float, float, float, float]:
        """The single rectangle enclosing every tile."""
        return (min(t[0] for t in self.tiles), min(t[1] for t in self.tiles),
                max(t[2] for t in self.tiles), max(t[3] for t in self.tiles))

    @property
    def expected_places(self) -> float:
        """Eateries with 25+ reviews this borough is expected to hold."""
        return (
            self.population
            / 1000.0
            * TALLINN_PLACES_PER_1000_RESIDENTS
            * self.gastro_intensity
        )

    @property
    def density(self) -> float:
        """Expected eateries per settled square kilometre."""
        return self.expected_places / self.settled_km2


# Ordered by borough number, as Berlin numbers them.
DISTRICTS: List[District] = [
    District(
        "Mitte", 39.47, 385_748, 0.85, 2.6, (52.5200, 13.4050),
        ((52.505, 13.320, 52.570, 13.420),),
    ),
    District(
        "Friedrichshain-Kreuzberg", 20.34, 289_762, 0.90, 2.0, (52.5050, 13.4300),
        ((52.487, 13.385, 52.525, 13.480),),
    ),
    District(
        # Prenzlauer Berg through Pankow proper, then Karow and Buch to the
        # north; the fields between them are not worth a circle.
        "Pankow", 103.07, 409_335, 0.55, 1.0, (52.5690, 13.4130),
        ((52.530, 13.395, 52.600, 13.500),
         (52.600, 13.470, 52.650, 13.520)),
    ),
    District(
        # The eastern strip only. The Grunewald is the other half of the
        # borough and has no restaurants in it.
        "Charlottenburg-Wilmersdorf", 64.72, 343_592, 0.55, 1.5, (52.5000, 13.3000),
        ((52.462, 13.255, 52.540, 13.340),),
    ),
    District(
        "Spandau", 91.87, 245_197, 0.45, 0.7, (52.5350, 13.2000),
        ((52.510, 13.170, 52.570, 13.250),
         (52.520, 13.110, 52.545, 13.175),
         (52.450, 13.150, 52.480, 13.200)),
    ),
    District(
        "Steglitz-Zehlendorf", 102.56, 311_142, 0.50, 0.8, (52.4350, 13.2600),
        ((52.410, 13.280, 52.470, 13.360),
         (52.400, 13.190, 52.445, 13.280)),
    ),
    District(
        "Tempelhof-Schoeneberg", 53.09, 351_644, 0.75, 1.0, (52.4700, 13.3600),
        ((52.410, 13.340, 52.500, 13.410),),
    ),
    District(
        "Neukoelln", 44.93, 329_691, 0.75, 1.2, (52.4600, 13.4400),
        ((52.400, 13.410, 52.490, 13.480),),
    ),
    District(
        # Treptow, then Koepenick's old town, then Altglienicke. Everything
        # between is the Mueggelsee, the Wuhlheide and the Koepenicker Forst.
        "Treptow-Koepenick", 168.42, 288_447, 0.30, 0.7, (52.4550, 13.5800),
        ((52.450, 13.470, 52.500, 13.560),
         (52.430, 13.560, 52.470, 13.630),
         (52.395, 13.510, 52.430, 13.580)),
    ),
    District(
        "Marzahn-Hellersdorf", 61.74, 292_955, 0.65, 0.5, (52.5350, 13.5900),
        ((52.490, 13.540, 52.570, 13.620),),
    ),
    District(
        "Lichtenberg", 52.29, 300_970, 0.75, 0.75, (52.5150, 13.5000),
        ((52.480, 13.465, 52.575, 13.535),),
    ),
    District(
        # Tegeler Forst and Tegeler See fill the middle of this borough.
        "Reinickendorf", 89.31, 267_167, 0.50, 0.65, (52.5900, 13.3100),
        ((52.560, 13.290, 52.620, 13.370),
         (52.620, 13.270, 52.660, 13.320)),
    ),
]

# Published totals, used by the tests to catch a typo in the table above.
BERLIN_AREA_KM2 = 891.8
BERLIN_POPULATION = 3_815_650


def total_area_km2() -> float:
    return sum(d.area_km2 for d in DISTRICTS)


def total_settled_km2() -> float:
    return sum(d.settled_km2 for d in DISTRICTS)


def total_swept_km2() -> float:
    return sum(d.swept_km2 for d in DISTRICTS)


def total_population() -> int:
    return sum(d.population for d in DISTRICTS)


def total_expected_places() -> float:
    return sum(d.expected_places for d in DISTRICTS)


def by_name(name: str) -> District:
    """Look a borough up, forgivingly: case and umlaut spelling do not matter."""
    wanted = _fold(name)
    for d in DISTRICTS:
        if _fold(d.name) == wanted or _fold(d.name).startswith(wanted):
            return d
    raise KeyError(f"no Berlin borough matching {name!r}")


def _fold(text: str) -> str:
    out = text.lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss"), (" ", ""), ("-", "")):
        out = out.replace(a, b)
    return out
