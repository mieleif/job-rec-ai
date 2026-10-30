"""Géographie : rattacher un texte de lieu libre (« Genève, GE, Switzerland ») à un canton.

Les ATS écrivent les lieux de façon hétérogène : Geneva / Genève / Genf, « Lausanne, VD »,
« Meyrin (GE) », « 2 Locations »… On ne cherche pas la perfection : une liste de communes
de l'arc lémanique où se trouvent les grands employeurs, plus les noms de canton.
"""

import re

from job_rec_ai.text import compile_keywords, first_match, normalize

# Périmètre retenu pour la première base : l'arc lémanique (décision du 22.10.2026)
TARGET_CANTONS = {"GE", "VD"}

_PLACES = {
    "GE": [
        "geneve", "geneva", "genf", "ginevra", "carouge", "meyrin", "vernier", "lancy",
        "plan-les-ouates", "satigny", "thonex", "onex", "chene-bourg", "chene-bougeries",
        "cointrin", "grand-saconnay", "versoix", "collonge-bellerive",
        "cologny", "veyrier", "bernex", "confignon", "le lignon", "acacias", "petit-lancy",
        "grand-lancy", "pregny-chambesy", "chambesy", "aire-la-ville", "avully",
        "perly", "bardonnex", "troinex", "puplinge", "puits-godet",
    ],
    "VD": [
        "vaud", "waadt", "lausanne", "vevey", "nyon", "gland", "morges", "renens",
        "ecublens", "prilly", "rolle", "montreux", "yverdon", "epalinges", "crissier",
        "bussigny", "le mont-sur-lausanne", "aubonne", "la tour-de-peilz", "le sentier",
        "le brassus", "le lieu", "orbe", "payerne", "chavannes-pres-renens",
        "preverenges", "eysins", "coppet", "founex", "mies", "commugny", "saint-prex",
        "etoy", "allaman", "tolochenaz", "romanel", "pully", "lutry", "cheseaux",
        "aigle", "bex", "moudon", "vallorbe", "penthalaz", "begnins",
        "chavannes-de-bogis", "prangins", "bioley-orjulaz",
    ],
}

_PATTERNS = compile_keywords(_PLACES.items())
# Abréviations de canton en majuscules : « Lausanne, VD » ou « Meyrin (GE) »
_ABBREV = re.compile(rf"\b({'|'.join(_PLACES)})\b")
# Homonymes à l'étranger : Geneva (Illinois, New York), Bellevue (Washington)…
_FOREIGN = re.compile(
    r"united states|\busa\b|illinois|new york|\b(il|ny|oh|al|wa)\b|ohio|alabama|"
    r"florida|france|italy|italia|united kingdom"
)


def canton_of(location: str | None) -> str | None:
    """Renvoie « GE », « VD » ou None si le lieu n'est pas dans l'arc lémanique."""
    if not location:
        return None
    norm = normalize(location)
    if _FOREIGN.search(norm):
        return None
    canton, _ = first_match(_PATTERNS, norm)
    if canton:
        return canton
    match = _ABBREV.search(location)
    return match.group(1) if match else None


def is_target(location: str | None) -> bool:
    return canton_of(location) in TARGET_CANTONS
