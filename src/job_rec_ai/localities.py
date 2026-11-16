"""Répertoire officiel des localités suisses → table de référence NPA / nom → canton.

Source : le « Répertoire officiel des localités » de swisstopo (Amtliches
Ortschaftenverzeichnis), open data mis à jour chaque mois, une ligne par couple
(localité, NPA, commune) avec le canton et la part des adresses :
https://data.geo.admin.ch/ch.swisstopo-vd.ortschaftenverzeichnis_plz/ortschaftenverzeichnis_plz/ortschaftenverzeichnis_plz_2056.csv.zip

On n'en garde qu'une table compacte versionnée avec le code (ch_localities.csv) :
- ``npa`` : chaque NPA → le canton qui a au moins 90 % de ses adresses. Un NPA partagé à
  parts comparables (1290 : Versoix GE et Chavannes-des-Bois VD) n'est pas retenu : le
  nom de la localité tranchera ;
- ``name`` : chaque nom de localité ou de commune normalisé → son canton. « Stein AG » est
  gardé tel quel ; sa forme courte « stein » seulement si elle n'est pas ambiguë (Stein AG,
  Stein AR et Stein SG existent : « stein » n'est pas retenu).

Régénérer après avoir dézippé l'archive :
    uv run python -m job_rec_ai.localities AMTOVZ_CSV_LV95.csv
"""

import csv
import re
import sys
from collections import Counter, defaultdict
from functools import cache
from importlib.resources import files
from pathlib import Path

from job_rec_ai.text import normalize

SWISS_CANTONS = frozenset({
    "AG", "AI", "AR", "BE", "BL", "BS", "FR", "GE", "GL", "GR", "JU", "LU", "NE",
    "NW", "OW", "SG", "SH", "SO", "SZ", "TG", "TI", "UR", "VD", "VS", "ZG", "ZH",
})
REFERENCE = files("job_rec_ai") / "ch_localities.csv"

# « Stein AG », « Stein (AG) » : le canton écrit en suffixe pour distinguer les homonymes
_SUFFIX = re.compile(r"\s\(?([a-z]{2})\)?$")
# « Lausanne 25 » : les localités numérotées des cases postales
_NUMBERED = re.compile(r"\s\d+$")
# Un nom porté par plusieurs cantons n'est retenu que si l'un d'eux domine nettement
_DOMINANT = 0.9


def name_key(text: str) -> str:
    """Forme de comparaison d'un nom de lieu : « Plan-les-Ouates » → « plan les ouates »."""
    return re.sub(r"\s+", " ", normalize(text).replace("-", " ")).strip()


def _dominant(counter: Counter) -> str | None:
    canton, weight = counter.most_common(1)[0]
    return canton if weight >= _DOMINANT * sum(counter.values()) else None


def build(rows) -> list[tuple[str, str, str]]:
    """Lignes du répertoire swisstopo → [(kind, key, canton)] triées."""
    npa: dict[str, Counter] = defaultdict(Counter)
    names: dict[str, Counter] = defaultdict(Counter)
    short: dict[str, set] = defaultdict(set)
    for row in rows:
        canton = row["Kantonskürzel"]
        if canton not in SWISS_CANTONS:  # Liechtenstein (FL) et autres
            continue
        share = float(row["Adressenanteil"].replace("%", "").strip() or 0)
        npa[row["PLZ4"]][canton] += share
        for name in (row["Ortschaftsname"], row["Gemeindename"]):
            key = _NUMBERED.sub("", name_key(name))
            suffix = _SUFFIX.search(key)
            if suffix and suffix.group(1).upper() in SWISS_CANTONS:
                written = suffix.group(1).upper()
                base = key[:suffix.start()]
                short[base].add(written)
                names[f"{base} {suffix.group(1)}"][written] += 1  # le suffixe fait foi
            else:
                names[key][canton] += share or 1
    table = {("npa", code): canton for code, c in npa.items() if (canton := _dominant(c))}
    for key, counter in names.items():
        if (canton := _dominant(counter)) and len(key) >= 3:
            table[("name", key)] = canton
    for base, cantons in short.items():
        if len(cantons) == 1 and ("name", base) not in table and len(base) >= 3:
            table[("name", base)] = next(iter(cantons))
    return sorted((kind, key, canton) for (kind, key), canton in table.items())


def write(source: Path, target: Path) -> int:
    with source.open(encoding="utf-8-sig", newline="") as f:
        table = build(csv.DictReader(f, delimiter=";"))
    with target.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["kind", "key", "canton"])
        writer.writerows(table)
    return len(table)


@cache
def reference() -> tuple[dict[str, str], dict[str, str]]:
    """(NPA → canton, nom normalisé → canton), lus une fois depuis ch_localities.csv."""
    npa, names = {}, {}
    with REFERENCE.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            (npa if row["kind"] == "npa" else names)[row["key"]] = row["canton"]
    return npa, names


if __name__ == "__main__":
    source = Path(sys.argv[1])
    target = Path(__file__).with_name("ch_localities.csv")
    print(f"{write(source, target)} entrées écrites dans {target}")
