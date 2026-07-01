"""Country-name → geo-id resolution for the choropleth builder.

ClinicalTrials.gov reports country *names*; a Vega-Lite choropleth keys on the
numeric feature ids of a topojson. We map names to ISO 3166-1 *numeric* codes,
which are exactly the feature ids used by the standard vega ``world-110m``
topojson (referenced by :func:`app.viz.vega_templates.choropleth_spec`).

The map is intentionally small but covers the countries that dominate clinical
trial registration. When a name does not resolve, the choropleth builder falls
back to a ranked bar chart rather than silently dropping the datum
(:func:`resolve_countries` reports the unmapped names so the caller can explain
the fallback in a hint).
"""

from __future__ import annotations

# Country name -> ISO 3166-1 numeric code (== world-110m topojson feature id).
# Keyed by a normalized (lowercased, stripped) name; common CT.gov spellings and
# aliases point at the same code.
COUNTRY_TO_GEO_ID: dict[str, int] = {
    "united states": 840,
    "united states of america": 840,
    "usa": 840,
    "canada": 124,
    "mexico": 484,
    "brazil": 76,
    "argentina": 32,
    "chile": 152,
    "colombia": 170,
    "peru": 604,
    "united kingdom": 826,
    "great britain": 826,
    "uk": 826,
    "ireland": 372,
    "france": 250,
    "germany": 276,
    "spain": 724,
    "italy": 380,
    "portugal": 620,
    "netherlands": 528,
    "belgium": 56,
    "switzerland": 756,
    "austria": 40,
    "denmark": 208,
    "sweden": 752,
    "norway": 578,
    "finland": 246,
    "poland": 616,
    "czechia": 203,
    "czech republic": 203,
    "hungary": 348,
    "greece": 300,
    "romania": 642,
    "russia": 643,
    "russian federation": 643,
    "ukraine": 804,
    "turkey": 792,
    "israel": 376,
    "saudi arabia": 682,
    "egypt": 818,
    "south africa": 710,
    "nigeria": 566,
    "kenya": 404,
    "china": 156,
    "japan": 392,
    "south korea": 410,
    "korea, republic of": 410,
    "republic of korea": 410,
    "india": 356,
    "pakistan": 586,
    "thailand": 764,
    "vietnam": 704,
    "viet nam": 704,
    "indonesia": 360,
    "malaysia": 458,
    "philippines": 608,
    "singapore": 702,
    "taiwan": 158,
    "australia": 36,
    "new zealand": 554,
}


def _normalize(name: str) -> str:
    return name.strip().lower()


def resolve_countries(names: list[str]) -> tuple[dict[str, int], list[str]]:
    """Resolve country names to geo ids.

    Returns ``(resolved, unmapped)`` where ``resolved`` maps each *original*
    name to its numeric geo id and ``unmapped`` lists the original names that
    could not be resolved (order-preserving, deduplicated).
    """
    resolved: dict[str, int] = {}
    unmapped: list[str] = []
    seen_unmapped: set[str] = set()
    for name in names:
        geo_id = COUNTRY_TO_GEO_ID.get(_normalize(name))
        if geo_id is None:
            if name not in seen_unmapped:
                seen_unmapped.add(name)
                unmapped.append(name)
        else:
            resolved[name] = geo_id
    return resolved, unmapped
