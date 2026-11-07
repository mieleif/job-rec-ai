"""La liste des employeurs suivis : data/companies.csv, éditable à la main.

Une ligne = une entreprise, son secteur, son canton, et l'adresse de son ATS
(colonne `board` : URL du site Workday, identifiant SmartRecruiters…). La colonne
`publisher_type` dit qui publie : « employeur » (par défaut) ou « agence » (une agence de
placement publie pour des clients souvent anonymes, et parfois la même offre que l'employeur).
La colonne `blocked` dit pourquoi on ne collecte pas (robots.txt, site qui refuse le robot,
annonces seulement sur un jobboard) : l'ATS, lui, reste un fait.
La colonne `domain` est le domaine web nu de l'employeur (« vitol.com », « coop.ch ») dont
DoxAI tire le logo ; vide quand on n'en est pas sûr (la recherche logo.dev prend alors le
relais, voir domains.py).
Ce fichier est de la configuration écrite par un humain : le code ne le réécrit jamais.
Savoir si un board fonctionne est un fait observé, qui vit en base (crawl_runs).
"""

import csv
from pathlib import Path

from job_rec_ai.domains import normalize_domain
from job_rec_ai.text import normalize

DEFAULT_CSV = Path("data/companies.csv")
FIELDS = ["company", "sector", "canton", "careers_url", "ats", "board", "publisher_type",
          "blocked", "domain"]
EMPLOYER, AGENCY = "employeur", "agence"


def load_companies(path: Path | str = DEFAULT_CSV) -> list[dict]:
    with open(path, encoding="utf-8", newline="") as f:
        rows = [{key: (row.get(key) or "").strip() or None for key in FIELDS}
                for row in csv.DictReader(f)]
    for row in rows:
        row["publisher_type"] = row["publisher_type"] or EMPLOYER
        if row["domain"]:
            domain = normalize_domain(row["domain"])
            if domain is None:  # une faute de frappe ne doit pas finir en logo cassé
                raise SystemExit(f"{path} : domaine invalide pour {row['company']!r} : "
                                 f"{row['domain']!r}")
            row["domain"] = domain
    return rows


def find(companies: list[dict], name: str) -> dict:
    """L'entreprise dont le nom normalisé correspond (« nestle » trouve « Nestlé »)."""
    for company in companies:
        if normalize(company["company"]) == normalize(name):
            return company
    raise SystemExit(f"entreprise inconnue : {name!r} (voir data/companies.csv)")
