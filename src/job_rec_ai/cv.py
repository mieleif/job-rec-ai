"""Le texte d'un CV, prêt à comparer aux offres.

Les CV réels vivent dans data/private/ (jamais commité). pypdf : pur Python, sans binaire ;
suffisant pour un CV en une colonne (pdfplumber ferait mieux sur une mise en page en
colonnes, au prix de pdfminer).
"""

import re
from pathlib import Path

from pypdf import PdfReader

DEFAULT_CV = Path("data/private/cv.pdf")

# Icônes des polices (téléphone, LinkedIn…) : la zone Unicode « à usage privé »
_PRIVATE_USE = re.compile(r"[-]")
# Puces en début de ligne seulement : un tiret demi-cadratin au milieu d'une phrase
# (« Data & BI – ERP ») est de la ponctuation
_BULLETS = re.compile(r"^[ \t]*[■●•▪◦►–][ \t]+", re.MULTILINE)
# Lignes de coordonnées : e-mail, téléphone, profils (« in/… », « @… »). Inutiles pour
# chercher un emploi, et nuisibles : le NPA de l'adresse ou les chiffres du téléphone
# matchent des offres.
_CONTACT = re.compile(r"[\w.+-]+@[\w-]+\.\w|\+\d{2}[\d ]{6,}|(^|\s)(in/|@)\w", re.MULTILINE)
# Mot coupé en fin de ligne : « con-\nception » → « conception ». Seulement devant une
# minuscule, pour ne pas recoller un vrai tiret en début de ligne (« - Python »).
_HYPHENATION = re.compile(r"(\w)-\n(?=[a-zà-ÿ])")


def clean(text: str) -> str:
    """Texte extrait d'un PDF → texte lisible : césures recollées, icônes et puces retirées."""
    text = _HYPHENATION.sub(r"\1", text)
    text = _PRIVATE_USE.sub(" ", text)
    text = _BULLETS.sub("", text)
    return "\n".join(re.sub(r"[ \t]+", " ", line).strip()
                     for line in text.splitlines() if line.strip())


def without_contact(text: str) -> str:
    """Le texte sans ses lignes de coordonnées (adresse, e-mail, téléphone, profils)."""
    return "\n".join(line for line in text.splitlines() if not _CONTACT.search(line))


def read_cv(path: Path = DEFAULT_CV) -> str:
    """Le texte du CV : PDF (toutes les pages) ou texte brut (.txt, .md)."""
    path = Path(path)
    if path.suffix.lower() == ".pdf":
        raw = "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
    else:
        raw = path.read_text(encoding="utf-8")
    return clean(raw)
