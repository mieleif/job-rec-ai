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
_BULLETS = re.compile(r"[■●•▪◦►–]\s")
# Mot coupé en fin de ligne : « con-\nception » → « conception ». Seulement devant une
# minuscule, pour ne pas recoller un vrai tiret en début de ligne (« - Python »).
_HYPHENATION = re.compile(r"(\w)-\n(?=[a-zà-ÿ])")


def clean(text: str) -> str:
    """Texte extrait d'un PDF → texte lisible : césures recollées, icônes et puces retirées."""
    text = _HYPHENATION.sub(r"\1", text)
    text = _PRIVATE_USE.sub(" ", text)
    text = _BULLETS.sub(" ", text)
    return "\n".join(re.sub(r"[ \t]+", " ", line).strip()
                     for line in text.splitlines() if line.strip())


def read_cv(path: Path = DEFAULT_CV) -> str:
    """Le texte du CV : PDF (toutes les pages) ou texte brut (.txt, .md)."""
    path = Path(path)
    if path.suffix.lower() == ".pdf":
        raw = "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
    else:
        raw = path.read_text(encoding="utf-8")
    return clean(raw)
