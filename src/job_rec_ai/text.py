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
    text = unescape("".join(parser.parts)).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def normalize(text: str) -> str:
    """Minuscules, sans accents, espaces réduits : « Genève  » → « geneve »."""
    text = unicodedata.normalize("NFKD", text.casefold())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text).strip()


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


def detect_language(text: str) -> str:
    """Renvoie « fr », « en » ou « other » (allemand, italien, texte vide ou trop court)."""
    words = re.findall(r"[a-zà-ÿ]+", text.casefold())
    if len(words) < 3:
        return "other"
    scores = {lang: sum(w in stop for w in words) for lang, stop in _STOPWORDS.items()}
    best = max(scores, key=scores.get)
    # Moins de 5 % de mots-outils : probablement ni du français, ni de l'anglais
    if scores[best] / len(words) < 0.05 or best == "de":
        return "other"
    return best
