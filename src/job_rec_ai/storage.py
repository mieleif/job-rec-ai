"""Stockage DuckDB : toutes les requêtes SQL du projet vivent ici.

Le reste du code ne parle qu'à ces fonctions, jamais directement à DuckDB. Le jour où l'app
multi-utilisateurs arrive (M7-M8), passer à Postgres ne touchera que ce fichier.

Trois couches (vocabulaire « médaillon » des data engineers) :
- bronze : les réponses JSON brutes des ATS, en fichiers dans data/raw/ (voir pipeline) ;
- silver : la table `jobs`, une ligne par offre, nettoyée et classée ;
- gold : les vues et agrégats pour l'analyse (`jobs_view`, `stats`).
"""

from datetime import date, datetime
from pathlib import Path

import duckdb

DEFAULT_DB = Path("data/jobs.duckdb")

SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    company     VARCHAR PRIMARY KEY,
    sector      VARCHAR,
    canton      VARCHAR,
    careers_url VARCHAR,
    ats         VARCHAR,
    board       VARCHAR,
    verified    BOOLEAN
);

CREATE TABLE IF NOT EXISTS jobs (
    url             VARCHAR PRIMARY KEY,   -- clé naturelle : une offre = une URL
    title           VARCHAR NOT NULL,
    company         VARCHAR NOT NULL,
    location        VARCHAR,
    canton          VARCHAR,
    description     VARCHAR,
    language        VARCHAR,
    posted_at       DATE,
    source          VARCHAR,
    source_id       VARCHAR,
    employment_type VARCHAR,
    family          VARCHAR,
    family_keyword  VARCHAR,
    seniority       VARCHAR,
    workload_min    INTEGER,
    workload_max    INTEGER,
    first_seen      TIMESTAMP NOT NULL,    -- première collecte où l'offre est apparue
    last_seen       TIMESTAMP NOT NULL,    -- dernière collecte où elle était encore en ligne
    active          BOOLEAN NOT NULL
);

CREATE TABLE IF NOT EXISTS crawl_runs (
    started_at TIMESTAMP,
    company    VARCHAR,
    ats        VARCHAR,
    status     VARCHAR,      -- ok | error | skipped
    fetched    INTEGER,      -- offres brutes rapportées par l'ATS (déjà filtrées par lieu)
    loaded     INTEGER,      -- offres valides chargées en base
    error      VARCHAR
);

CREATE OR REPLACE VIEW jobs_view AS
SELECT j.*, c.sector
FROM jobs j LEFT JOIN companies c USING (company);
"""

JOB_COLUMNS = [
    "url", "title", "company", "location", "canton", "description", "language", "posted_at",
    "source", "source_id", "employment_type", "family", "family_keyword", "seniority",
    "workload_min", "workload_max",
]


def connect(path: Path | str = DEFAULT_DB) -> duckdb.DuckDBPyConnection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    con.execute(SCHEMA)
    return con


def upsert_companies(con, companies: list[dict]) -> None:
    con.executemany(
        """INSERT INTO companies VALUES ($company, $sector, $canton, $careers_url, $ats,
                                         $board, $verified)
           ON CONFLICT (company) DO UPDATE SET
               sector = excluded.sector, canton = excluded.canton,
               careers_url = excluded.careers_url, ats = excluded.ats,
               board = excluded.board, verified = excluded.verified""",
        companies,
    )


def upsert_jobs(con, rows: list[dict], seen_at: datetime) -> None:
    """Insère les nouvelles offres, met à jour les existantes : relancer = zéro doublon.

    first_seen n'est jamais écrasé : c'est la mémoire de la date d'apparition.
    """
    if not rows:
        return
    columns = ", ".join(JOB_COLUMNS)
    values = ", ".join(f"${c}" for c in JOB_COLUMNS)
    updates = ", ".join(f"{c} = excluded.{c}" for c in JOB_COLUMNS if c != "url")
    con.executemany(
        f"""INSERT INTO jobs ({columns}, first_seen, last_seen, active)
            VALUES ({values}, $seen_at, $seen_at, TRUE)
            ON CONFLICT (url) DO UPDATE SET {updates},
                last_seen = excluded.last_seen, active = TRUE""",
        [{**row, "seen_at": seen_at} for row in rows],
    )


def expire_missing(con, company: str, source: str, seen_at: datetime) -> int:
    """Désactive les offres de l'entreprise absentes de la collecte `seen_at`.

    À n'appeler qu'après une collecte RÉUSSIE de l'entreprise : si l'ATS a planté à
    mi-chemin, l'absence d'une offre ne prouve pas qu'elle a été retirée.
    """
    # DuckDB renvoie le nombre de lignes modifiées comme résultat de l'UPDATE
    (count,) = con.execute(
        """UPDATE jobs SET active = FALSE
           WHERE company = ? AND source = ? AND active AND last_seen < ?""",
        [company, source, seen_at],
    ).fetchone()
    return count


def log_run(con, **run) -> None:
    con.execute(
        """INSERT INTO crawl_runs VALUES ($started_at, $company, $ats, $status, $fetched,
                                          $loaded, $error)""",
        {"fetched": None, "loaded": None, "error": None, **run},
    )


def update_classification(con, rows: list[dict]) -> None:
    con.executemany(
        """UPDATE jobs SET family = $family, family_keyword = $family_keyword,
                           seniority = $seniority, workload_min = $workload_min,
                           workload_max = $workload_max
           WHERE url = $url""",
        rows,
    )


# --- lecture : facettes, tri, agrégats ------------------------------------------------------

SORTS = {
    "recent": "posted_at DESC NULLS LAST, first_seen DESC",
    "new": "first_seen DESC",
    "company": "company, title",
    "title": "title",
}
FACETS = ("company", "sector", "canton", "family", "seniority", "language", "source")


def search(con, *, text: str | None = None, since: date | None = None,
           min_workload: int | None = None, include_inactive: bool = False,
           sort: str = "recent", limit: int = 20, **facets) -> list[dict]:
    """Filtre par facettes (égalité exacte, insensible à la casse) et trie.

    search(con, canton="GE", family="Data & IA", sort="recent")
    """
    where, params = [], []
    if not include_inactive:
        where.append("active")
    for name, value in facets.items():
        if name not in FACETS:
            raise ValueError(f"facette inconnue : {name} (possibles : {', '.join(FACETS)})")
        if value is not None:
            where.append(f"lower({name}) = lower(?)")
            params.append(value)
    if text:
        where.append("(title ILIKE ? OR description ILIKE ?)")
        params += [f"%{text}%"] * 2
    if since:
        where.append("coalesce(posted_at, CAST(first_seen AS DATE)) >= ?")
        params.append(since)
    if min_workload is not None:
        # Une offre sans taux affiché est supposée à 100 %
        where.append("coalesce(workload_max, 100) >= ?")
        params.append(min_workload)
    if sort not in SORTS:
        raise ValueError(f"tri inconnu : {sort} (possibles : {', '.join(SORTS)})")
    sql = f"""SELECT title, company, sector, location, canton, family, seniority, language,
                     posted_at, workload_min, workload_max, url
              FROM jobs_view {"WHERE " + " AND ".join(where) if where else ""}
              ORDER BY {SORTS[sort]} LIMIT ?"""
    cursor = con.execute(sql, [*params, limit])
    names = [d[0] for d in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def counts(con, facet: str, limit: int = 20) -> list[tuple[str, int]]:
    """Nombre d'offres actives par valeur d'une facette, du plus fréquent au plus rare."""
    if facet not in FACETS:
        raise ValueError(f"facette inconnue : {facet}")
    return con.execute(
        f"""SELECT coalesce({facet}, '(inconnu)') AS value, count(*) AS n
            FROM jobs_view WHERE active GROUP BY ALL ORDER BY n DESC, value LIMIT ?""",
        [limit],
    ).fetchall()


def all_titles(con) -> list[tuple[str, str]]:
    return con.execute("SELECT url, title FROM jobs").fetchall()
