"""Étalon de couverture : Adzuna (agrégateur, via la liste public-apis) contre notre base.

Adzuna ne sert pas à remplir la base (descriptions tronquées, copies d'offres), mais à
répondre à deux questions qu'on ne peut pas trancher depuis nos seules données :
1. Quels employeurs publient le plus d'offres dans la région ? → la liste des entreprises
   à suivre vient des données, et non de mon intuition.
2. Pour une entreprise suivie, quelle part de ses offres captons-nous ? (rappel ≈ nous / Adzuna)

Clés gratuites sur https://developer.adzuna.com, à mettre dans .env :
    ADZUNA_APP_ID=...   ADZUNA_APP_KEY=...
puis : uv run --env-file .env job-rec-ai benchmark
"""

import os
from dataclasses import dataclass

from job_rec_ai.http import PoliteClient
from job_rec_ai.text import normalize

API = "https://api.adzuna.com/v1/api/jobs/ch"
DEFAULT_WHERE = ["Genève", "Lausanne"]
# Suffixes juridiques à ignorer pour rapprocher « Rolex SA » de « Rolex »
_LEGAL = {"sa", "ag", "sarl", "gmbh", "ltd", "inc", "group", "groupe", "holding", "suisse",
          "switzerland", "international", "s.a.", "plc", "llc"}


def credentials() -> dict:
    try:
        return {"app_id": os.environ["ADZUNA_APP_ID"], "app_key": os.environ["ADZUNA_APP_KEY"]}
    except KeyError as missing:
        raise SystemExit(f"variable {missing} absente : voir l'en-tête de benchmark.py") from None


def top_companies(client: PoliteClient, where: str, keys: dict) -> list[tuple[str, int]]:
    data = client.get_json(f"{API}/top_companies", params={**keys, "where": where})
    return [(row["canonical_name"], row["count"]) for row in data.get("leaderboard", [])]


def company_key(name: str) -> str:
    words = [w for w in normalize(name).replace(",", " ").split() if w not in _LEGAL]
    return " ".join(words)


@dataclass
class Coverage:
    company: str
    adzuna: int
    ours: int | None  # None : entreprise absente de data/companies.csv

    @property
    def recall(self) -> float | None:
        return None if self.ours is None or not self.adzuna else self.ours / self.adzuna


def compare(leaderboard: list[tuple[str, int]], ours: dict[str, int],
            tracked: list[str]) -> list[Coverage]:
    """Rapproche le classement Adzuna de nos comptes par entreprise (noms normalisés)."""
    tracked_keys = {company_key(name): name for name in tracked}
    ours_by_key = {company_key(name): n for name, n in ours.items()}
    rows = []
    for name, count in leaderboard:
        key = company_key(name)
        match = tracked_keys.get(key)
        rows.append(Coverage(company=match or name, adzuna=count,
                             ours=ours_by_key.get(key, 0) if match else None))
    return rows
