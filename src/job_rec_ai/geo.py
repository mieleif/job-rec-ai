"""Géographie : rattacher un texte de lieu libre (« Genève, GE, Switzerland ») à un canton.

Les ATS écrivent les lieux de façon hétérogène : Geneva / Genève / Genf, « Lausanne, VD »,
« Meyrin (GE) », « 2 Locations »… On ne cherche pas la perfection : une liste de communes
de Suisse romande où se trouvent les employeurs, plus les noms de canton.
"""

import re

from job_rec_ai.text import compile_keywords, first_match, normalize

# Périmètre : la Suisse romande (décision du 04.11.2026 ; l'arc lémanique GE + VD avant).
# « BE » ne couvre que le Jura bernois et Bienne : aucune commune germanophone n'est listée.
TARGET_CANTONS = {"GE", "VD", "FR", "NE", "VS", "JU", "BE"}
# Le pays des cantons cibles, tel que l'écrivent les ATS dans leurs filtres de recherche
TARGET_COUNTRY = "Switzerland"

_PLACES = {
    "GE": [
        "geneve", "geneva", "genf", "ginevra", "carouge", "meyrin", "vernier", "lancy",
        "plan-les-ouates", "satigny", "thonex", "onex", "chene-bourg", "chene-bougeries",
        "cointrin", "grand-saconnex", "versoix", "collonge-bellerive",
        "cologny", "veyrier", "bernex", "confignon", "le lignon", "acacias", "petit-lancy",
        "grand-lancy", "pregny-chambesy", "chambesy", "aire-la-ville", "avully",
        "perly", "bardonnex", "troinex", "puplinge", "puits-godet",
        # quartiers de la ville et communes de la rive gauche / rive droite
        "plainpalais", "eaux-vives", "paquis", "champel", "servette", "petit-saconnex",
        "jonction", "fusterie", "vesenaz", "anieres", "hermance", "vandoeuvres", "genthod",
        "collex-bossy", "dardagny", "cartigny", "meinier", "celigny",
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
        "aclens", "vufflens-la-ville", "echallens", "oron-la-ville", "les diablerets",
        "villars-sur-ollon", "leysin", "rennaz", "ollon", "avenches", "cossonay", "lucens",
        "chexbres", "cully", "sainte-croix", "chateau-d'oex",
    ],
    "FR": [
        "fribourg", "freiburg", "bulle", "villars-sur-glane", "marly", "granges-paccot",
        "givisiez", "murten", "morat", "estavayer-le-lac", "estavayer", "romont",
        "chatel-saint-denis", "dudingen", "guin", "belfaux", "matran", "domdidier",
        "broc", "riaz", "vuadens", "corminboeuf", "avry", "courtepin", "tafers", "wunnewil",
        "flamatt", "kerzers", "morlon", "la tour-de-treme", "rossens",
    ],
    "NE": [
        "neuchatel", "neuenburg", "la chaux-de-fonds", "le locle", "marin-epagnier",
        "saint-blaise", "peseux", "boudry", "cortaillod",
        "couvet", "val-de-travers", "cressier", "hauterive", "serrieres", "val-de-ruz",
        "cernier", "fleurier", "les brenets", "bevaix", "auvernier", "la tene", "milvignes",
        "corcelles-cormondreche", "fontainemelon",
    ],
    "VS": [
        "valais", "wallis", "sion", "sitten", "sierre", "siders", "martigny", "monthey",
        "conthey", "collombey", "collombey-muraz", "saint-maurice", "verbier",
        "crans-montana", "visp", "viege", "brig", "naters", "zermatt", "saxon",
        "vetroz", "ardon", "chippis", "steg", "gampel", "leuk", "susten", "vouvry",
        "port-valais", "bagnes", "le chable", "riddes", "chamoson", "saviese",
        "uvrier", "bramois", "evolene", "nendaz", "saas-fee",
    ],
    "JU": [
        "delemont", "porrentruy", "bassecourt", "saignelegier", "courrendlin",
        "courgenay", "glovelier", "le noirmont", "les breuleux", "courroux", "boncourt",
        "canton du jura",
    ],
    "BE": [  # le Jura bernois et Bienne seulement (voir TARGET_CANTONS)
        "bienne", "biel", "saint-imier", "st-imier", "moutier", "tavannes",
        "tramelan", "reconvilier", "la neuveville", "courtelary", "sonceboz", "malleray",
        "bevilard", "cormoret", "villeret", "corgemont", "jura bernois",
    ],
}

# Tirets et espaces équivalents : les URL écrivent « Chene-Bourg » ou « Chene Bourg »,
# les annonces « Plan-les-Ouates » ou « Plan les Ouates »
_PATTERNS = compile_keywords(
    (canton, [p.replace("-", " ") for p in places]) for canton, places in _PLACES.items())
# Abréviations de canton en majuscules : « Lausanne, VD » ou « Meyrin (GE) ». Pour les
# autres cantons, seulement entre parenthèses (« Bulle (FR) ») : « FR », « BE », « NE »
# sont aussi des codes de pays (« Paris, FR », « Bruxelles, BE ») ou des États américains.
_ABBREV = re.compile(r"\b(GE|VD)\b|\((FR|NE|VS|JU)\)")
# Homonymes à l'étranger : Geneva (Illinois, New York), Bellevue (Washington), Freiburg
# im Breisgau, Neuenburg am Rhein… « , DE » en fin de lieu : le code pays de l'Allemagne.
# Communes homonymes en Suisse romande même (Colombier, Corcelles et Fontaines existent dans
# VD et NE ; « Fully » est aussi un mot anglais des URL) : non listées, faute de pouvoir
# trancher sur le nom seul.
_FOREIGN = re.compile(
    r"united states|\busa\b|illinois|new york|\b(il|ny|oh|al|wa)\b|ohio|alabama|"
    r"florida|france|italy|italia|united kingdom|germany|deutschland|allemagne|belgium|"
    r"belgique|breisgau|am rhein|baden wurttemberg|,\s*de\s*$"
)
# Une offre multi-sites (« Geneva, Switzerland, Paris, France ») cite un pays étranger sans
# être à l'étranger : la Suisse nommée explicitement lève le veto des homonymes.
_SWISS = re.compile(r"switzerland|suisse|schweiz|svizzera")


# Séparateurs des lieux multiples : « Zürich / Lausanne », « Genève; Paris », « Genève · CDI »
_SEGMENTS = re.compile(r"\s*[/;·|]\s*")


def canton_of(location: str | None) -> str | None:
    """Renvoie le canton romand du lieu (« GE », « NE »…), None s'il n'est pas reconnu.

    Chaque lieu d'une offre multi-sites est jugé séparément : le veto « homonyme étranger »
    d'un segment (« Geneva, IL, United States ») ne doit ni contaminer ni être levé par un
    autre (« … / Zurich, Switzerland »).
    """
    for segment in _SEGMENTS.split(location or ""):
        canton = _segment_canton(segment)
        if canton:
            return canton
    return None


def _segment_canton(location: str) -> str | None:
    if not location:
        return None
    norm = normalize(location).replace("-", " ")
    if _FOREIGN.search(norm) and not _SWISS.search(norm):
        return None
    canton, _ = first_match(_PATTERNS, norm)
    if canton:
        return canton
    match = _ABBREV.search(location)
    return (match.group(1) or match.group(2)) if match else None


def mentions_target_place(text: str | None) -> bool:
    """Un nom de lieu romand apparaît-il dans le texte ?

    Pré-filtre grossier pour un texte qui mêle lieu et autre chose (une URL « Lieu-Titre ») :
    pas de veto des homonymes étrangers, qui se déclencherait sur les mots du titre
    (« Vevey-Country-Manager-France »). Le verdict définitif vient de canton_of.
    """
    canton, _ = first_match(_PATTERNS, normalize(text or "").replace("-", " "))
    return canton in TARGET_CANTONS


def is_target(location: str | None) -> bool:
    return canton_of(location) in TARGET_CANTONS
