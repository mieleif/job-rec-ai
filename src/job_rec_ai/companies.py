"""La liste des employeurs suivis : data/companies.csv, éditable à la main.

Une ligne = une entreprise, son secteur, son canton, et l'adresse de son ATS
(colonne `board` : URL du site Workday, identifiant SmartRecruiters…).
`verified` passe à true quand une collecte a réellement fonctionné.
"""

import csv
from pathlib import Path

DEFAULT_CSV = Path("data/companies.csv")
FIELDS = ["company", "sector", "canton", "careers_url", "ats", "board", "verified"]


def load_companies(path: Path | str = DEFAULT_CSV) -> list[dict]:
    with open(path, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        row["verified"] = row.get("verified", "").strip().lower() == "true"
        for key in ("ats", "board", "sector", "canton", "careers_url"):
            row[key] = (row.get(key) or "").strip() or None
    return rows


def save_companies(rows: list[dict], path: Path | str = DEFAULT_CSV) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({**{k: row.get(k) or "" for k in FIELDS},
                             "verified": str(bool(row.get("verified"))).lower()})
