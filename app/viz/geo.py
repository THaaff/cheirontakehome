"""Country-name → geo-id resolution for the choropleth builder.

ClinicalTrials.gov reports country *names*; a Vega-Lite choropleth keys on the
numeric feature ids of a topojson. We map names to ISO 3166-1 *numeric* codes,
which are exactly the feature ids used by the standard vega ``world-110m``
topojson (referenced by :func:`app.viz.vega_templates.choropleth_spec`). Every
code in :data:`COUNTRY_TO_GEO_ID` has been verified to exist as a feature in
that topojson, so a *resolved* name is always drawable.

A name that is not resolved falls into one of two buckets, which the choropleth
builder treats differently (see :func:`resolve_countries`):

* **Unrenderable territories** — real places CT.gov reports that world-110m has
  no country feature for. It is a 110m *sovereign-state* basemap, so small
  dependencies and micro-states (Hong Kong, Singapore, Guam, Monaco, ...) simply
  have no polygon. These are expected; the builder still renders the map for
  everything else and names them in a hint so their counts are never silently
  dropped.
* **Unknown names** — anything we recognize as neither. A typo or a bad value is
  a signal that something upstream is off, so the builder conservatively falls
  back to a ranked bar chart rather than drawing a partial map.
"""

from __future__ import annotations

# Country name -> ISO 3166-1 numeric code (== world-110m topojson feature id).
# Keyed by a normalized (lowercased, stripped) name; common CT.gov spellings and
# aliases point at the same code. Every code here is a feature in world-110m.
COUNTRY_TO_GEO_ID: dict[str, int] = {
    # North & Central America, Caribbean
    "united states": 840,
    "united states of america": 840,
    "usa": 840,
    "canada": 124,
    "mexico": 484,
    "guatemala": 320,
    "belize": 84,
    "honduras": 340,
    "el salvador": 222,
    "nicaragua": 558,
    "costa rica": 188,
    "panama": 591,
    "cuba": 192,
    "dominican republic": 214,
    "haiti": 332,
    "jamaica": 388,
    "puerto rico": 630,
    "trinidad and tobago": 780,
    # South America
    "brazil": 76,
    "argentina": 32,
    "chile": 152,
    "colombia": 170,
    "peru": 604,
    "venezuela": 862,
    "venezuela, bolivarian republic of": 862,
    "ecuador": 218,
    "bolivia": 68,
    "bolivia, plurinational state of": 68,
    "paraguay": 600,
    "uruguay": 858,
    "guyana": 328,
    "suriname": 740,
    # Western & Northern Europe
    "united kingdom": 826,
    "great britain": 826,
    "uk": 826,
    "ireland": 372,
    "france": 250,
    "germany": 276,
    "spain": 724,
    "portugal": 620,
    "italy": 380,
    "netherlands": 528,
    "belgium": 56,
    "luxembourg": 442,
    "switzerland": 756,
    "austria": 40,
    "denmark": 208,
    "sweden": 752,
    "norway": 578,
    "finland": 246,
    "iceland": 352,
    # Central, Eastern & Southeastern Europe
    "poland": 616,
    "czechia": 203,
    "czech republic": 203,
    "slovakia": 703,
    "hungary": 348,
    "slovenia": 705,
    "croatia": 191,
    "bosnia and herzegovina": 70,
    "serbia": 688,
    "montenegro": 499,
    "north macedonia": 807,
    "macedonia": 807,
    "albania": 8,
    "greece": 300,
    "romania": 642,
    "bulgaria": 100,
    "moldova": 498,
    "republic of moldova": 498,
    "ukraine": 804,
    "belarus": 112,
    "lithuania": 440,
    "latvia": 428,
    "estonia": 233,
    "russia": 643,
    "russian federation": 643,
    "cyprus": 196,
    # Middle East, Caucasus & North Africa
    "turkey": 792,
    "turkey (türkiye)": 792,
    "türkiye": 792,
    "turkiye": 792,
    "israel": 376,
    "lebanon": 422,
    "jordan": 400,
    "syria": 760,
    "syrian arab republic": 760,
    "iraq": 368,
    "iran": 364,
    "iran, islamic republic of": 364,
    "saudi arabia": 682,
    "kuwait": 414,
    "qatar": 634,
    "united arab emirates": 784,
    "oman": 512,
    "yemen": 887,
    "georgia": 268,
    "armenia": 51,
    "azerbaijan": 31,
    "egypt": 818,
    "libya": 434,
    "tunisia": 788,
    "algeria": 12,
    "morocco": 504,
    # Sub-Saharan Africa
    "sudan": 729,
    "south sudan": 728,
    "ethiopia": 231,
    "kenya": 404,
    "uganda": 800,
    "tanzania": 834,
    "united republic of tanzania": 834,
    "nigeria": 566,
    "ghana": 288,
    "south africa": 710,
    "zimbabwe": 716,
    "zambia": 894,
    "mozambique": 508,
    "angola": 24,
    "cameroon": 120,
    "ivory coast": 384,
    "cote d'ivoire": 384,
    "côte d'ivoire": 384,
    "senegal": 686,
    "mali": 466,
    "madagascar": 450,
    "namibia": 516,
    "botswana": 72,
    # Central & South Asia
    "kazakhstan": 398,
    "uzbekistan": 860,
    "turkmenistan": 795,
    "kyrgyzstan": 417,
    "tajikistan": 762,
    "afghanistan": 4,
    "pakistan": 586,
    "india": 356,
    "bangladesh": 50,
    "sri lanka": 144,
    "nepal": 524,
    "bhutan": 64,
    # East & Southeast Asia
    "myanmar": 104,
    "thailand": 764,
    "laos": 418,
    "lao people's democratic republic": 418,
    "cambodia": 116,
    "vietnam": 704,
    "viet nam": 704,
    "malaysia": 458,
    "indonesia": 360,
    "philippines": 608,
    "brunei": 96,
    "brunei darussalam": 96,
    "china": 156,
    "mongolia": 496,
    "japan": 392,
    "south korea": 410,
    "korea, republic of": 410,
    "republic of korea": 410,
    "north korea": 408,
    "taiwan": 158,
    # Oceania
    "australia": 36,
    "new zealand": 554,
    "papua new guinea": 598,
    "fiji": 242,
}

# Real places CT.gov reports that the world-110m sovereign-state basemap has no
# feature for (small dependencies and micro-states). Recognizing them lets the
# choropleth render for everything else and name them in a hint, rather than
# treating them as unknown and falling back to a bar. Normalized names.
UNRENDERABLE_TERRITORIES: frozenset[str] = frozenset(
    {
        "hong kong",
        "singapore",
        "guam",
        "monaco",
        "northern mariana islands",
        "malta",
        "bahrain",
        "liechtenstein",
        "andorra",
        "san marino",
    }
)


def _normalize(name: str) -> str:
    return name.strip().lower()


def resolve_countries(
    names: list[str],
) -> tuple[dict[str, int], list[str], list[str]]:
    """Classify country names for the choropleth builder.

    Returns ``(resolved, unrenderable, unknown)``:

    * ``resolved`` maps each *original* name to its numeric geo id (drawable).
    * ``unrenderable`` lists names that are known territories the world-110m
      basemap cannot draw (order-preserving, deduplicated).
    * ``unknown`` lists names we do not recognize at all (order-preserving,
      deduplicated) — the signal to fall back to a ranked bar.
    """
    resolved: dict[str, int] = {}
    unrenderable: list[str] = []
    unknown: list[str] = []
    seen_unrenderable: set[str] = set()
    seen_unknown: set[str] = set()
    for name in names:
        key = _normalize(name)
        geo_id = COUNTRY_TO_GEO_ID.get(key)
        if geo_id is not None:
            resolved[name] = geo_id
        elif key in UNRENDERABLE_TERRITORIES:
            if name not in seen_unrenderable:
                seen_unrenderable.add(name)
                unrenderable.append(name)
        elif name not in seen_unknown:
            seen_unknown.add(name)
            unknown.append(name)
    return resolved, unrenderable, unknown
