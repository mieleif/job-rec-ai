"""Nettoyage de texte : HTML → texte brut, et détection de langue.

Volontairement sans dépendance (bibliothèque standard uniquement) : les règles sont
lisibles et testables, et leurs erreurs sont faciles à expliquer.
"""

import re
import unicodedata
from html import unescape
from html.parser import HTMLParser

# Balises dont le contenu n'est pas du texte lisible
_SKIPPED = {"script", "style", "noscript", "template"}
# Balises « bloc » : on insère un espace pour ne pas coller « Python</li><li>SQL »
_BLOCKS = {"p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6",
           "tr", "td", "th", "section", "article", "header", "footer", "table"}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in _SKIPPED:
            self._skip_depth += 1
        elif tag in _BLOCKS:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in _SKIPPED and self._skip_depth:
            self._skip_depth -= 1
        elif tag in _BLOCKS:
            self.parts.append(" ")

    def handle_data(self, data):
        if not self._skip_depth:
            self.parts.append(data)


def clean_html(html: str | None) -> str:
    """HTML → texte sur une ligne, sans balises ni scripts, entités décodées."""
    if not html:
        return ""
    # Certains ATS (Greenhouse) renvoient du HTML lui-même échappé : « &lt;p&gt; »
    if "<" not in html and "&lt;" in html:
        html = unescape(html)
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    # convert_charrefs=True : handle_data reçoit déjà le texte avec les entités décodées
    text = "".join(parser.parts).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def normalize(text: str) -> str:
    """Minuscules, sans accents, espaces réduits : « Genève  » → « geneve »."""
    text = unicodedata.normalize("NFKD", text.casefold())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text).strip()


_TOKEN = re.compile(r"[a-z0-9+#]{2,}")


def tokenize(text: str | None) -> list[str]:
    """Texte → mots normalisés (« C++ et Python » → ["c++", "et", "python"]). « + » et « # »
    gardés pour C++ et C# ; les lettres isolées (« l' », « d' ») écartées."""
    return _TOKEN.findall(normalize(text or ""))


def chunk_text(text: str, max_words: int, overlap: int) -> list[str]:
    """Découpe en fenêtres de `max_words` mots, deux voisines partageant `overlap` mots (une
    idée à cheval sur la coupure reste entière dans l'une des deux)."""
    if overlap >= max_words:
        raise ValueError("overlap doit être plus petit que max_words")
    words = text.split()
    step = max_words - overlap
    # Arrêt dès qu'une fenêtre atteint la fin : pas de dernier chunk fait du seul chevauchement
    starts = range(0, max(len(words) - overlap, 1), step) if words else ()
    return [" ".join(words[i:i + max_words]) for i in starts]


def compile_keywords(rules) -> list[tuple[str, re.Pattern]]:
    """[(étiquette, [mots-clés])] → [(étiquette, motif)] qui ne matche que des mots entiers
    d'un texte normalisé : « it » ne doit pas matcher « audit », ni « onex » « bonex »."""
    compiled = []
    for label, keywords in rules:
        # Plus long d'abord : « supply chain » doit gagner sur « chain »
        alternatives = "|".join(map(re.escape, sorted(keywords, key=len, reverse=True)))
        compiled.append((label, re.compile(rf"(?<![a-z0-9])({alternatives})(?![a-z0-9])")))
    return compiled


def first_match(compiled, text: str, default=None) -> tuple[str | None, str | None]:
    """(étiquette, mot-clé) de la première règle qui matche ; (default, None) sinon.
    L'ordre des règles est donc une priorité."""
    for label, pattern in compiled:
        match = pattern.search(text)
        if match:
            return label, match.group(1)
    return default, None


# Mots-outils très fréquents et propres à chaque langue. Compter leurs occurrences est
# la plus vieille méthode de détection de langue, et elle suffit pour séparer FR et EN.
_STOPWORDS = {
    "fr": {"le", "la", "les", "des", "une", "et", "est", "pour", "dans", "nous", "vous",
           "avec", "sur", "au", "aux", "du", "de", "votre", "notre", "qui", "en", "un"},
    "en": {"the", "and", "of", "to", "in", "for", "with", "you", "we", "our", "your",
           "is", "are", "a", "an", "on", "will", "as", "be", "this", "who"},
    "de": {"der", "die", "das", "und", "mit", "für", "sie", "wir", "ihre", "unsere",
           "ist", "von", "zu", "auf", "eine", "ein", "im", "den", "bei"},
}

# Toutes langues confondues : à retirer d'une requête (un CV) avant de chercher.
# Liste figée : le classement BM25 de /recommend en dépend (la détection a ses propres mots).
STOPWORDS = frozenset().union(*_STOPWORDS.values())

# Les mots-outils qui servent à reconnaître la langue d'une annonce. Différents de
# _STOPWORDS sur un point : chaque mot n'appartient qu'à UNE langue (un test le vérifie).
# « in » est anglais, allemand ET italien : compté pour l'anglais, il a suffi à étiqueter
# « en » le titre « Verkäufer:in Food » (3 mots, 1 mot-outil : 33 %). Écartés pour la même
# raison : a, an, on, la, le, un, il, du, si, e (partagés entre au moins deux langues).
_MARKERS = {
    "fr": {"les", "des", "une", "et", "est", "pour", "dans", "nous", "vous", "avec", "sur",
           "au", "aux", "votre", "notre", "vos", "nos", "qui", "de", "en", "sont", "être",
           "cette", "par", "ou", "à", "êtes", "afin", "chez"},
    "en": {"the", "and", "of", "to", "for", "with", "you", "we", "our", "your", "is", "are",
           "will", "be", "this", "who", "as", "or", "at", "from", "that", "have", "can"},
    "de": {"der", "die", "das", "und", "mit", "für", "sie", "wir", "ihre", "unsere", "ist",
           "von", "zu", "auf", "eine", "ein", "im", "den", "bei", "sind", "werden", "nicht",
           "oder", "sowie", "auch", "dich", "deine", "uns", "dem", "bist"},
    "it": {"lo", "gli", "della", "delle", "degli", "del", "che", "per", "con", "una", "sono",
           "nel", "nella", "alla", "dei", "di", "ed", "anche", "questo", "siamo", "tua",
           "nostro", "nostra", "al", "è"},
}
LANGUAGE_CODES = tuple(_MARKERS)  # fr, en, de, it

# Quand le texte est-il assez clair pour trancher ? Il faut à la fois :
MIN_MARKERS = 2    # au moins 2 mots-outils de la langue gagnante (1 seul : un hasard ; sur
                   # 5 000 offres, en exiger 3 laisse 500 offres de plus sans verdict du texte
                   # pour seulement 4 désaccords de moins avec la langue déclarée par l'ATS),
MIN_SHARE = 0.05   # au moins 5 % des mots (en dessous : une liste de compétences, pas des phrases),
DOMINANCE = 2.0    # et deux fois plus que la langue suivante.
# Entre 1,2 et 2 fois : une annonce dans la langue locale suivie d'un pavé standard en anglais
# (Roche, UCB, Lombard Odier), ou vraiment bilingue (Lonza). Une indication, pas une preuve :
# la langue déclarée par l'ATS passe avant, le texte ne sert que s'il n'y en a pas.
WEAK_DOMINANCE = 1.2


def guess_language(text: str | None, dominance: float = DOMINANCE) -> str | None:
    """« fr », « en », « de » ou « it » si le texte le dit assez clairement (voir les seuils
    ci-dessus) ; None sinon (texte court, sans phrases, ou sans langue assez majoritaire)."""
    words = re.findall(r"[a-zà-ÿ]+", (text or "").casefold())
    scores = sorted(((sum(w in markers for w in words), lang)
                     for lang, markers in _MARKERS.items()), reverse=True)
    (best, lang), (second, _) = scores[0], scores[1]
    if best < MIN_MARKERS or best < MIN_SHARE * len(words) or best < dominance * second:
        return None
    return lang


def language_tag(declared: str | None) -> str | None:
    """Une langue déclarée par un ATS (« de-DE », « fr_CH », « EN ») → « de », « fr », « en » ;
    None si absente ou hors des quatre langues reconnues."""
    code = re.split(r"[-_]", (declared or "").strip().lower())[0]
    return code if code in LANGUAGE_CODES else None


def resolve_language(declared: str | None, text: str | None) -> str:
    """La langue d'une annonce, par ordre de confiance :
    1. le texte, s'il est clair (il dit ce que le candidat lira) ;
    2. sinon la langue déclarée par l'ATS (Coop n'écrit souvent que le titre) ;
    3. sinon le texte, s'il penche nettement d'un côté ;
    4. sinon « other ».
    Le texte clair passe avant l'ATS : un site déclare parfois la langue de son interface,
    pas celle de l'annonce (EY et Nestlé : « en-US » sur des annonces en allemand ou en
    français ; l'ONU : « EN » partout)."""
    return (guess_language(text) or language_tag(declared)
            or guess_language(text, WEAK_DOMINANCE) or "other")


def detect_language(text: str) -> str:
    """Renvoie « fr », « en » ou « other » (allemand, italien, texte vide ou peu clair).
    Le contrat du checkpoint M2 ; `guess_language` distingue aussi l'allemand et l'italien."""
    lang = resolve_language(None, text)
    return lang if lang in ("fr", "en") else "other"
