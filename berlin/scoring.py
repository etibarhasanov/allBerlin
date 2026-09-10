"""Turning per-cell entity counts into a location score.

A count is not a score.  Three things stand between them, and each one is a
decision that ought to be visible rather than buried in a weighting.

**Neighbourhood.** What matters at a site is not what stands in its own 0.1 km2
cell but what stands within a walk of it.  Every feature therefore has a
catchment form, summed over the k-ring around the cell.  On a hex grid that is
one unambiguous number: a k-ring is 3k(k+1)+1 cells, all of them the same
distance apart, with none of the corner-versus-edge fudging a square grid forces.

**Comparability.** Raw counts are not comparable across features -- a cell with
40 shops and 2 pharmacies is not "20 times better served" -- and their
distributions are heavily skewed, so a mean-and-standard-deviation
normalisation would be dominated by the top hundred cells in Mitte.  Features
are converted to percentile ranks across the city, which is scale-free, robust
to the skew, and directly interpretable: 0.9 means denser than 90% of Berlin.

**Purpose.** There is no single "good location".  A site is good *for
something*, and the same cell that is ideal for a convenience store is hopeless
for a warehouse.  So there is no default score -- there are named profiles,
each a set of weights and, importantly, penalties.  A profile that cannot
express "too much of this is bad" cannot express competition, and competition
is most of what site selection is about.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Mapping, Optional, Sequence

from . import hexgrid
from .entities import CATEGORIES, PRIVATE_CATEGORIES, by_key

# Counts as they come out of a census: cell id -> category key -> count.
CellCounts = Mapping[str, Mapping[str, float]]


def percentile_ranks(values: Sequence[float]) -> List[float]:
    """Rank each value in 0..1 against the rest, ties sharing a rank.

    Ties matter here rather than being a technicality: most of Berlin's cells
    hold zero of any given category, and if those ties were broken arbitrarily
    the bottom half of every score would be noise presented as signal.
    """
    n = len(values)
    if n == 0:
        return []
    if n == 1:
        return [0.5]
    order = sorted(range(n), key=lambda i: values[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        # Midpoint of the tied block, so a tie is neither rewarded nor punished.
        rank = (i + j) / 2.0 / (n - 1)
        for k in range(i, j + 1):
            ranks[order[k]] = rank
        i = j + 1
    return ranks


def shannon_diversity(counts: Mapping[str, float]) -> float:
    """Evenness across categories, 0 (all one kind) to 1 (perfectly mixed).

    A high street with fifty shops of one kind is a different place from one
    with fifty spread across ten kinds, and a raw total cannot tell them apart.
    """
    values = [v for v in counts.values() if v > 0]
    total = sum(values)
    if total <= 0 or len(values) < 2:
        return 0.0
    entropy = -sum((v / total) * math.log(v / total) for v in values)
    return entropy / math.log(len(values))


@dataclass
class Features:
    """Everything a profile is allowed to weigh, for one cell."""

    cell: str
    counts: Dict[str, float]
    total: float
    diversity: float
    catchment: Dict[int, float]           # k -> total entities within k rings
    transport: float                      # transport nodes within 1 ring
    education: float                      # schools etc within 2 rings
    population: float = 0.0

    def get(self, name: str) -> float:
        """Resolve a feature name a profile can refer to."""
        if name == "total":
            return self.total
        if name == "diversity":
            return self.diversity
        if name == "transport":
            return self.transport
        if name == "education":
            return self.education
        if name == "population":
            return self.population
        if name.startswith("catchment_k"):
            return self.catchment.get(int(name[len("catchment_k"):]), 0.0)
        if name.startswith("count_"):
            key = name[len("count_"):]
            # A category this cell simply has none of is 0; a category that
            # does not exist is a typo in a profile, and silently weighting it
            # at zero would hide the bug behind a plausible-looking score.
            by_key(key)
            return self.counts.get(key, 0.0)
        raise KeyError(f"unknown feature {name!r}")


def build_features(counts: CellCounts,
                   rings: Sequence[int] = (1, 2),
                   population: Optional[Mapping[str, float]] = None) -> List[Features]:
    """Assemble per-cell features from raw census counts.

    Cells outside the census are treated as empty rather than skipped: a site
    on the city edge genuinely has less around it, and dropping the missing
    neighbours would flatter it into looking central.
    """
    population = population or {}
    private_keys = [c.key for c in PRIVATE_CATEGORIES]
    out = []
    for cell, per_category in counts.items():
        private = {k: float(per_category.get(k, 0)) for k in private_keys}
        catchment = {}
        for k in rings:
            catchment[k] = sum(
                sum(float(counts.get(n, {}).get(key, 0)) for key in private_keys)
                for n in hexgrid.ring(cell, k)
            )
        out.append(Features(
            cell=cell,
            counts={k: float(v) for k, v in per_category.items()},
            total=sum(private.values()),
            diversity=shannon_diversity(private),
            catchment=catchment,
            transport=sum(float(counts.get(n, {}).get("transport", 0))
                          for n in hexgrid.ring(cell, 1)),
            education=sum(float(counts.get(n, {}).get("education_childcare", 0))
                          for n in hexgrid.ring(cell, 2)),
            population=float(population.get(cell, 0.0)),
        ))
    return out


@dataclass(frozen=True)
class Profile:
    """A named question, expressed as weights over normalised features.

    Weights reward; penalties punish.  Both are applied to percentile ranks, so
    a weight of 1.0 and a penalty of 1.0 are the same size, which makes a
    profile readable as a sentence rather than as a tuning exercise.
    """

    key: str
    question: str
    weights: Dict[str, float]
    penalties: Dict[str, float] = field(default_factory=dict)

    def score(self, ranked: Mapping[str, float]) -> float:
        reward = sum(w * ranked.get(f, 0.0) for f, w in self.weights.items())
        punish = sum(w * ranked.get(f, 0.0) for f, w in self.penalties.items())
        total = sum(self.weights.values()) or 1.0
        return max(0.0, min(1.0, (reward - punish) / total))


PROFILES: Dict[str, Profile] = {
    "footfall": Profile(
        "footfall",
        "Where are people already passing?",
        weights={"catchment_k1": 1.0, "transport": 0.8, "diversity": 0.5,
                 "count_food_drink": 0.4, "count_retail": 0.4},
    ),
    "retail_site": Profile(
        "retail_site",
        "Where would a new shop trade well?",
        weights={"catchment_k1": 1.0, "transport": 0.7, "diversity": 0.6,
                 "count_food_drink": 0.3},
        # A street already full of shops is proof of demand and proof of
        # competition at the same time. Weighing only the first is how you
        # recommend the most contested block in the city.
        penalties={"count_retail": 0.5},
    ),
    "food_site": Profile(
        "food_site",
        "Where would a new cafe or restaurant trade well?",
        weights={"catchment_k1": 1.0, "transport": 0.8, "count_retail": 0.4,
                 "education": 0.2, "count_professional_finance": 0.3},
        penalties={"count_food_drink": 0.6},
    ),
    "underserved": Profile(
        "underserved",
        "Where do residents live with the least around them?",
        weights={"population": 1.0},
        penalties={"catchment_k2": 0.8},
    ),
    "office": Profile(
        "office",
        "Where is the weekday, daytime economy?",
        weights={"count_professional_finance": 1.0, "transport": 0.8,
                 "count_food_drink": 0.3, "catchment_k1": 0.4},
    ),
}


def score_cells(features: Sequence[Features],
                profile: Profile) -> Dict[str, float]:
    """Score every cell under one profile.

    Percentile ranks are computed once across the whole city, so a score is a
    statement about a cell's place in Berlin, not about its place among
    whatever subset happened to be passed in.
    """
    names = sorted(set(profile.weights) | set(profile.penalties))
    ranked_by_name = {
        name: percentile_ranks([f.get(name) for f in features]) for name in names
    }
    out = {}
    for i, f in enumerate(features):
        ranked = {name: ranked_by_name[name][i] for name in names}
        out[f.cell] = profile.score(ranked)
    return out


def top_cells(scores: Mapping[str, float], n: int = 10) -> List[tuple]:
    return sorted(scores.items(), key=lambda kv: -kv[1])[:n]


def profile(key: str) -> Profile:
    try:
        return PROFILES[key]
    except KeyError:
        raise KeyError(
            f"no profile {key!r}; known: {', '.join(sorted(PROFILES))}"
        ) from None
