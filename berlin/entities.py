"""What counts as a private entity, and how Google's type taxonomy carves it up.

Two facts about Nearby Search shape everything here.

``includedTypes`` is matched against a place's own type list, not against what
a human would call it.  Google does not consider a cafe to be a restaurant, and
asking for ``restaurant`` alone missed 22 of 25 curated places in the Tallinn
sweep.  A category is therefore a list of Google types, not a word.

And a request is capped at 20 results whatever it holds.  That makes a narrow
type filter *cheaper*, not more expensive: sweeping one category at a time cuts
the density each query sees by roughly the category's share of the whole, which
is what keeps cells below the cap and stops them splitting.  Counting by
category and counting in total cost about the same number of calls; the
category sweep just tells you more.

Categories are chosen for what a location score needs to distinguish -- what
draws people past a door, what competes with it, what it depends on -- rather
than for taxonomic tidiness.  Shares are the fraction of all private entities
each is expected to hold in a European city; they drive the resolution choice
and nothing else, and `allberlin probe` replaces them with counts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

# Nearby Search accepts at most this many entries in includedTypes.
MAX_TYPES_PER_REQUEST = 50


@dataclass(frozen=True)
class Category:
    key: str
    label: str
    # Expected share of all private entities. Used only to size the grid.
    share: float
    # Google Places (New) types, matched against each place's own type list.
    types: List[str]
    # False for things that are not private businesses but drive a score
    # anyway: a station brings footfall, a school brings a catchment.
    private: bool = True
    note: str = ""

    def __post_init__(self):
        if len(self.types) > MAX_TYPES_PER_REQUEST:
            raise ValueError(
                f"{self.key}: {len(self.types)} types, over Google's "
                f"{MAX_TYPES_PER_REQUEST} per request"
            )


CATEGORIES: List[Category] = [
    Category(
        "food_drink", "Food and drink", 0.14,
        ["restaurant", "cafe", "coffee_shop", "bakery", "bar", "pub", "wine_bar",
         "meal_takeaway", "meal_delivery", "fast_food_restaurant",
         "ice_cream_shop", "dessert_shop", "sandwich_shop", "tea_house",
         "brewery", "confectionery", "donut_shop", "deli", "diner",
         "brunch_restaurant", "bar_and_grill", "buffet_restaurant",
         "food_court", "bagel_shop", "juice_shop", "steak_house",
         "vegan_restaurant", "vegetarian_restaurant", "cafeteria",
         "fine_dining_restaurant", "barbecue_restaurant", "chocolate_shop",
         "candy_store"],
        note="The footfall generator, and the one category with a public "
             "reference dataset to check the sweep against.",
    ),
    Category(
        "retail", "Retail", 0.25,
        ["store", "grocery_store", "supermarket", "convenience_store",
         "clothing_store", "shoe_store", "jewelry_store", "book_store",
         "electronics_store", "cell_phone_store", "furniture_store",
         "home_goods_store", "home_improvement_store", "hardware_store",
         "department_store", "shopping_mall", "discount_store", "gift_shop",
         "sporting_goods_store", "bicycle_store", "pet_store", "florist",
         "liquor_store", "butcher_shop", "asian_grocery_store", "market",
         "warehouse_store", "wholesaler", "auto_parts_store", "food_store"],
        note="'store' is deliberately included: it is the generic type Google "
             "falls back to, and dropping it loses whole streets of shops.",
    ),
    Category(
        "services_personal", "Personal services", 0.13,
        ["hair_salon", "hair_care", "barber_shop", "beauty_salon", "beautician",
         "nail_salon", "massage", "spa", "sauna", "tanning_studio",
         "body_art_service", "laundry", "tailor", "locksmith", "florist",
         "funeral_home", "foot_care", "makeup_artist", "veterinary_care",
         "child_care_agency"],
        note="Dense, street-level, and the clearest signal that a location has "
             "residential footfall rather than office footfall.",
    ),
    Category(
        "professional_finance", "Professional and financial", 0.15,
        ["bank", "atm", "accounting", "lawyer", "insurance_agency",
         "real_estate_agency", "consultant", "corporate_office",
         "travel_agency", "tour_agency", "telecommunications_service_provider",
         "courier_service", "post_office"],
        note="Office footfall: weekday, daytime, and worth separating from the "
             "residential kind because it empties at six.",
    ),
    Category(
        "health", "Health", 0.09,
        ["pharmacy", "drugstore", "doctor", "dentist", "dental_clinic",
         "hospital", "physiotherapist", "chiropractor", "medical_lab",
         "skin_care_clinic", "wellness_center"],
        note="A pharmacy is one of the strongest single predictors of a "
             "functioning local high street.",
    ),
    Category(
        "leisure_culture", "Leisure and culture", 0.07,
        ["movie_theater", "night_club", "museum", "art_gallery", "casino",
         "bowling_alley", "amusement_park", "zoo", "aquarium", "event_venue",
         "concert_hall", "performing_arts_theater", "community_center",
         "cultural_center", "tourist_attraction", "internet_cafe",
         "video_arcade", "banquet_hall", "wedding_venue"],
        note="Evening and weekend draw, which is what separates a destination "
             "from a commuter corridor.",
    ),
    Category(
        "sports_fitness", "Sport and fitness", 0.03,
        ["gym", "fitness_center", "sports_club", "sports_complex",
         "swimming_pool", "yoga_studio", "sports_activity_location",
         "athletic_field", "stadium", "arena", "ice_skating_rink",
         "golf_course", "sports_coaching"],
    ),
    Category(
        "lodging", "Lodging", 0.02,
        ["hotel", "hostel", "guest_house", "bed_and_breakfast", "motel",
         "resort_hotel", "extended_stay_hotel", "inn", "lodging", "campground"],
        note="Visitor demand that no residential statistic will show you.",
    ),
    Category(
        "auto", "Automotive", 0.05,
        ["car_repair", "car_dealer", "car_wash", "car_rental", "gas_station",
         "parking", "electric_vehicle_charging_station", "auto_parts_store"],
        note="Car-oriented, so a high share here usually means the opposite of "
             "a walkable site.",
    ),
    Category(
        "trades_logistics", "Trades and logistics", 0.07,
        ["plumber", "electrician", "painter", "roofing_contractor",
         "general_contractor", "moving_company", "storage", "car_repair",
         "catering_service"],
        note="Backland businesses: they occupy commercial floorspace without "
             "generating any street footfall, which is exactly why they need "
             "separating from retail rather than counting with it.",
    ),
    Category(
        "education_childcare", "Education and childcare", 0.03,
        ["school", "primary_school", "secondary_school", "preschool",
         "university", "library", "child_care_agency"],
        private=False,
        note="Not private entities, mostly. Kept because a catchment of "
             "schools is a demand signal a business count cannot see.",
    ),
    Category(
        "transport", "Transport nodes", 0.0,
        ["train_station", "subway_station", "light_rail_station", "bus_station",
         "bus_stop", "transit_station", "ferry_terminal", "airport",
         "park_and_ride", "taxi_stand"],
        private=False,
        note="The single strongest footfall driver in Berlin, and free to "
             "collect. Never counted in the private-entity total.",
    ),
]

BY_KEY: Dict[str, Category] = {c.key: c for c in CATEGORIES}

PRIVATE_CATEGORIES: List[Category] = [c for c in CATEGORIES if c.private]
ANCHOR_CATEGORIES: List[Category] = [c for c in CATEGORIES if not c.private]


def by_key(key: str) -> Category:
    try:
        return BY_KEY[key]
    except KeyError:
        raise KeyError(
            f"no category {key!r}; known: {', '.join(sorted(BY_KEY))}"
        ) from None


def types_argument(category: Category) -> str:
    return ",".join(category.types)


def total_private_share() -> float:
    return sum(c.share for c in PRIVATE_CATEGORIES)
