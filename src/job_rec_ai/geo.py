"""Géographie : rattacher un texte de lieu libre (« Genève, GE, Switzerland ») à un canton.

Les ATS écrivent les lieux de façon hétérogène : Geneva / Genève / Genf, « Lausanne, VD »,
« Meyrin (GE) », « 2 Locations »… Deux sources, de la plus précise à la plus large :
1. une liste écrite à la main (exonymes et quartiers : Geneva, Genf, Plainpalais…),
   cherchée n'importe où dans le texte ;
2. le répertoire officiel des localités (swisstopo, voir localities.py) : tous les NPA et
   noms de localités / communes, mais un nom ne compte que s'il forme à lui seul un
   morceau du lieu (« CH - Ittigen », « Ittigen, Bern ») : « Rue », « Sur » ou « Ins »
   sont des localités, pas des mots à chercher dans « Rue du Rhône ».
"""

import re

from job_rec_ai import localities
from job_rec_ai.text import compile_keywords, first_match, normalize

# Périmètre : toute la Suisse, sans restriction linguistique (15.11.2026).
TARGET_CANTONS = set(localities.SWISS_CANTONS)
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
        "givisiez", "estavayer-le-lac", "estavayer", "romont",
        "chatel-saint-denis", "belfaux", "matran", "domdidier",
        "broc", "riaz", "vuadens", "corminboeuf", "avry", "courtepin",
        "morlon", "la tour-de-treme", "rossens",
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
        "crans-montana", "saxon",
        "vetroz", "ardon", "chippis", "vouvry",
        "port-valais", "bagnes", "le chable", "riddes", "chamoson", "saviese",
        "uvrier", "bramois", "evolene", "nendaz",
    ],
    "JU": [
        "delemont", "porrentruy", "bassecourt", "saignelegier", "courrendlin",
        "courgenay", "glovelier", "le noirmont", "les breuleux", "courroux", "boncourt",
        "canton du jura",
        "moutier",  # jurassienne depuis le 01.01.2026 (vote de 2021), bernoise avant
    ],
    "BE": [
        "bienne", "biel", "saint-imier", "st-imier", "tavannes",
        "tramelan", "reconvilier", "la neuveville", "courtelary", "sonceboz", "malleray",
        "bevilard", "cormoret", "villeret", "corgemont", "jura bernois",
    ],
}

# Les noms de canton permettent de situer aussi des communes absentes de cette liste.
_PLACES["BE"] += ["bern", "berne", "thun", "koniz", "burgdorf", "langenthal", "interlaken",
                  "nidau", "lyss", "aarberg", "lengnau", "pieterlen", "spiez", "ittigen"]
_PLACES["FR"] += ["singine", "sensebezirk", "dudingen", "guin", "tafers", "tavel",
                  "wunnewil", "flamatt", "schmitten", "plaffeien", "kerzers", "murten", "morat"]
_PLACES["VS"] += ["oberwallis", "haut-valais", "visp", "viege", "brig", "brigue", "glis",
                  "naters", "zermatt", "tasch", "saas-fee", "saas-grund", "stalden", "steg",
                  "gampel", "raron", "leuk", "loeche", "leukerbad", "susten", "salgesch",
                  "turtmann", "fiesch", "lalden"]
_PLACES.update({
    "ZH": ["zurich", "zuerich", "zurigo", "winterthur", "kloten", "schlieren", "uster",
           "dubendorf", "wallisellen", "opfikon", "horgen", "wadenswil", "dietikon"],
    "BS": ["basel-stadt", "bale-ville", "basel", "bale", "basilea", "riehen"],
    "BL": ["basel-landschaft", "basel-land", "baselland", "bale-campagne", "liestal",
           "allschwil", "muttenz", "pratteln", "binningen", "reinach bl"],
    "AG": ["aargau", "argovie", "aarau", "baden", "kaiseraugst", "rheinfelden",
           "wettingen", "wohlen", "lenzburg", "brugg", "stein ag"],
    "SO": ["solothurn", "soleure", "olten", "grenchen", "zuchwil", "derendingen"],
    "LU": ["luzern", "lucerne", "luzerna", "emmen", "kriens", "sursee", "ebikon"],
    "ZG": ["zug", "zoug", "baar", "cham", "rotkreuz", "risch"],
    "SZ": ["schwyz", "schwytz", "einsiedeln", "freienbach", "pfaffikon sz", "kussnacht"],
    "UR": ["uri", "altdorf", "schattdorf", "andermatt"],
    "OW": ["obwalden", "obwald", "sarnen", "alpnach", "engelberg", "sachseln"],
    "NW": ["nidwalden", "nidwald", "stans", "buochs", "hergiswil", "stansstad"],
    "GL": ["glarus", "glaris", "nafels", "netstal", "mollis"],
    "SH": ["schaffhausen", "schaffhouse", "neuhausen", "neuhausen am rheinfall"],
    "TG": ["thurgau", "thurgovie", "frauenfeld", "kreuzlingen", "weinfelden", "arbon"],
    "SG": ["st. gallen", "st gallen", "sankt gallen", "saint-gall", "rapperswil-jona",
           "rorschach", "buchs sg", "uzwil", "wil sg", "gossau sg"],
    "AR": ["appenzell ausserrhoden", "appenzell rhodes-exterieures", "herisau", "teufen"],
    "AI": ["appenzell innerrhoden", "appenzell rhodes-interieures", "appenzell"],
    "GR": ["graubunden", "grisons", "grigioni", "chur", "coire", "davos", "landquart",
           "st. moritz", "st moritz", "samedan", "domat", "ems"],
    "TI": ["ticino", "tessin", "lugano", "bellinzona", "locarno", "mendrisio", "chiasso",
           "bioggio", "manno", "stabio", "biasca", "ascona"],
})

# Tirets et espaces équivalents dans les lieux et les URL des ATS.
_PATTERNS = compile_keywords(
    (canton, [p.replace("-", " ") for p in places]) for canton, places in _PLACES.items())
# Les codes ambigus (FR, BE, NE, AI...) ne suffisent pas seuls : parenthèses ou pays suisse.
_CODES = "|".join(sorted(TARGET_CANTONS))
_ABBREV = re.compile(r"\b(GE|VD)\b|\((" + _CODES + r")\)")
_SWISS_ABBREV = re.compile(r"\b(" + _CODES + r")\b")
# Homonymes à l'étranger : un lieu qui nomme un pays, une région ou un code postal étrangers
# n'est pas en Suisse, même s'il porte un nom de localité suisse (Emmen aux Pays-Bas, Cham
# en Bavière, Baden en Autriche, Lucerne en Californie, Freiburg im Breisgau…). Indices :
# - un pays ou une région étrangers en toutes lettres (en, fr, de, it) ;
# - un État américain, en toutes lettres ou en code en fin de lieu (« New Bern, NC ») ;
#   « NE » et « AR » en sont exclus (Neuchâtel, Appenzell Rhodes-Extérieures), « Montana »
#   aussi (Crans-Montana) ;
# - les villes frontalières écrites avec la ville suisse voisine (« Saint-Louis (Bâle) »).
# Pas de veto « code postal à cinq chiffres » : l'État de Genève colle le numéro de rue au
# NPA (« Rue David-Dufour 51205 Genève »), ce qui écartait 14 offres genevoises.
# Communes homonymes en Suisse même (Colombier, Corcelles et Fontaines existent dans VD et
# NE) : non listées, faute de pouvoir trancher sur le nom seul.
_COUNTRIES = (
    "united states|usa|united kingdom|uk|england|scotland|ireland|irlande|france|italy|"
    "italia|italie|germany|deutschland|allemagne|germania|belgium|belgique|netherlands|"
    "nederland|niederlande|pays bas|austria|osterreich|autriche|liechtenstein|"
    "luxembourg|spain|espana|espagne|portugal|poland|polska|pologne|czech|czechia|hungary|"
    "slovakia|slovenia|croatia|serbia|romania|bulgaria|greece|cyprus|malta|denmark|"
    "sweden|norway|finland|india|china|singapore|japan|korea|taiwan|hong kong|australia|"
    "new zealand|canada|mexico|brazil|argentina|south africa|israel|turkey|"
    "united arab emirates|uae|dubai|bavaria|bayern|baden wurttemberg|breisgau|i\\.? ?br|"
    "sardinia|sardegna|mallorca|baleares|haute savoie|alsace|lombardia|lombardy|piemonte|"
    "vorarlberg|tirol"
)
_US_STATES = (
    "alabama|alaska|arizona|arkansas|california|colorado|connecticut|delaware|florida|"
    "georgia|hawaii|idaho|illinois|indiana|iowa|kansas|kentucky|louisiana|maine|maryland|"
    "massachusetts|michigan|minnesota|mississippi|missouri|nebraska|nevada|new hampshire|"
    "new jersey|new mexico|new york|north carolina|north dakota|ohio|oklahoma|oregon|"
    "pennsylvania|rhode island|south carolina|south dakota|tennessee|texas|utah|vermont|"
    "virginia|washington|west virginia|wisconsin|wyoming"
)
_US_CODES = (
    "al|ak|az|ca|co|ct|fl|ga|hi|ia|id|il|in|ks|ky|la|ma|md|me|mi|mn|mo|ms|mt|nc|nd|nh|nj|"
    "nm|nv|ny|oh|ok|or|pa|ri|sc|sd|tn|tx|ut|va|vt|wa|wi|wv|wy"
)
_BORDER_TOWNS = (
    "baden baden|saint louis|st louis|huningue|lorrach|weil am rhein|konstanz|mulhouse|annemasse|"
    "saint julien en genevois|ferney voltaire|divonne|thonon|evian|neuenburg am rhein|"
    "am rhein|como|varese"
)
_FOREIGN = re.compile(
    rf"\b(?:{_COUNTRIES}|{_US_STATES}|{_BORDER_TOWNS})\b"
    rf"|\b(?:il|ny|oh|al|wa)\b|,\s*(?:{_US_CODES}|de)\s*$"
)
# Une offre multi-sites (« Geneva, Switzerland, Paris, France ») cite un pays étranger sans
# être à l'étranger : la Suisse nommée explicitement lève le veto des homonymes. « ch » seul
# compte, pas « ch. » (chemin : « Ch. des Mines 2 »).
_SWISS = re.compile(r"\b(?:switzerland|suisse|schweiz|svizzera|svizra|che)\b|\bch\b(?!\.)")


# NPA (code postal suisse) → canton, quand aucun nom de lieu n'a parlé (Mediclinic :
# « Hirslanden Clinique Cecil, 1003 Laus », la ville tronquée), d'après le répertoire
# officiel (localities.py). Beaucoup de pays ont des codes postaux à 4 chiffres (Bruxelles
# 1000, Vienne 1010, Sydney 2000, Sandton 2196) : un NPA ne compte que préfixé « CH- » ou
# dans un lieu qui nomme la Suisse.
_NPA = re.compile(r"(?<![\d.])([1-9]\d{3})(?![\d.])")
_CH_NPA = re.compile(r"\bCH[-\s]?([1-9]\d{3})(?!\d)")


def is_switzerland(country: str | None) -> bool:
    """« CH », « CHE », « Switzerland », « Schweiz », « Suisse »… → True."""
    norm = normalize(country or "").strip()
    return norm in ("ch", "che") or bool(_SWISS.search(norm))


def canton_of_npa(text: str) -> str | None:
    """Le canton d'un NPA reconnu (« CH-1003 Laus », « 1870 Monthey, Switzerland » → VD, VS),
    None sans NPA reconnu ou sans indice que le lieu est en Suisse."""
    match = _CH_NPA.search(text)
    if not match and _SWISS.search(normalize(text)):
        match = _NPA.search(text)
    if not match:
        return None
    npa, _ = localities.reference()
    return npa.get(match.group(1))


# Morceaux d'un lieu qu'un nom de localité doit occuper seul : « Ittigen, Bern »,
# « CH - Ittigen », « Spital (Ittigen) ». Les NPA sont retirés (« 3063 Ittigen »).
_PARTS = re.compile(r"\s*(?:,|\s[-–]\s|\(|\))\s*")
_POSTAL = re.compile(r"\b(?:ch\s?)?\d{4}\b")


def _directory_canton(location: str) -> str | None:
    """Le canton d'un morceau du lieu qui est exactement un nom du répertoire officiel."""
    _, names = localities.reference()
    for part in _PARTS.split(location):
        key = localities.name_key(_POSTAL.sub(" ", normalize(part)))
        if key in names:
            return names[key]
    return None


# Séparateurs des lieux multiples : « Zürich / Lausanne », « Genève; Paris », « Genève · CDI »
_SEGMENTS = re.compile(r"\s*[/;·|]\s*")


def canton_of(location: str | None) -> str | None:
    """Renvoie le canton suisse du lieu (« GE », « NE »…), None s'il n'est pas reconnu.

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
    matches = [(len(match.group()), canton) for canton, pattern in _PATTERNS
               if (match := pattern.search(norm))]
    if matches:
        return max(matches, key=lambda item: item[0])[1]
    match = _ABBREV.search(location)
    if match:
        return match.group(1) or match.group(2)
    if canton := _directory_canton(location):
        return canton
    if _SWISS.search(norm):
        match = _SWISS_ABBREV.search(location)
        if match:
            return match.group(1)
    return canton_of_npa(location)


def mentions_target_place(text: str | None) -> bool:
    """Un nom de lieu suisse apparaît-il dans le texte ?

    Pré-filtre grossier pour un texte qui mêle lieu et autre chose (une URL « Lieu-Titre ») :
    pas de veto des homonymes étrangers, qui se déclencherait sur les mots du titre
    (« Vevey-Country-Manager-France »). Le verdict définitif vient de canton_of.
    """
    canton, _ = first_match(_PATTERNS, normalize(text or "").replace("-", " "))
    return canton in TARGET_CANTONS


def is_target(location: str | None) -> bool:
    # Le pays suffit : une commune inconnue ou une offre nationale reste collectable.
    return any(_SWISS.search(normalize(segment)) or _segment_canton(segment)
               for segment in _SEGMENTS.split(location or ""))
