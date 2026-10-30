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
    board       VARCHAR
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
    status     VARCHAR,      -- ok | suspect | error | skipped
    fetched    INTEGER,      -- offres brutes rapportées par l'ATS (déjà filtrées par lieu)
    loaded     INTEGER,      -- offres valides chargées en base
    error      VARCHAR
);

CREATE OR REPLACE VIEW jobs_view AS
SELECT j.*, c.sector
FROM jobs j LEFT JOIN companies c USING (company);
"""

def connect(path: Path | str = DEFAULT_DB) -> duckdb.DuckDBPyConnection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    con.execute(SCHEMA)
    return con


def _upsert(con, table: str, key: str, rows: list[dict], keep: tuple[str, ...] = ()) -> None:
    """INSERT … ON CONFLICT en UNE requête pour tout le lot (ensembliste).

    Les lignes Python sont d'abord chargées d'un bloc dans une table temporaire
    (`unnest` d'une liste de structs), puis fusionnées : ~100x plus rapide qu'un
    `executemany`, qui exécute une requête par ligne. Les colonnes viennent des clés des
    lignes : une colonne inconnue de la table fait échouer bruyamment, au lieu d'être
    ignorée en silence. `keep` : colonnes jamais écrasées en cas de conflit.
    """
    if not rows:
        return
    columns = list(rows[0])
    con.execute("CREATE OR REPLACE TEMP TABLE _staging AS SELECT unnest($rows, max_depth := 2)",
                {"rows": rows})
    updates = ", ".join(f"{c} = excluded.{c}" for c in columns if c != key and c not in keep)
    con.execute(f"""INSERT INTO {table} ({", ".join(columns)})
                    SELECT {", ".join(columns)} FROM _staging
                    ON CONFLICT ({key}) DO UPDATE SET {updates}""")
    con.execute("DROP TABLE _staging")


def upsert_companies(con, companies: list[dict]) -> None:
    _upsert(con, "companies", "company", companies)


def upsert_jobs(con, rows: list[dict], seen_at: datetime) -> None:
    """Insère les nouvelles offres, met à jour les existantes : relancer = zéro doublon.

    first_seen n'est jamais écrasé : c'est la mémoire de la date d'apparition.
    """
    stamps = {"first_seen": seen_at, "last_seen": seen_at, "active": True}
    _upsert(con, "jobs", "url", [{**row, **stamps} for row in rows], keep=("first_seen",))


def expiration_preview(con, company: str, source: str, seen_at: datetime) -> tuple[int, int]:
    """(offres qu'expire_missing désactiverait, offres actives) : à regarder avant d'expirer."""
    return con.execute(
        """SELECT count(*) FILTER (last_seen < ?), count(*) FROM jobs
           WHERE company = ? AND source = ? AND active""",
        [seen_at, company, source],
    ).fetchone()


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


def verified_companies(con) -> set[str]:
    """Entreprises dont au moins une collecte a réussi : leur board est donc le bon."""
    return {name for (name,) in con.execute(
        "SELECT DISTINCT company FROM crawl_runs WHERE status = 'ok'").fetchall()}


def update_derived(con, rows: list[dict]) -> None:
    """Réécrit les colonnes dérivées (clés des lignes, hors url) en une seule requête."""
    if not rows:
        return
    columns = [c for c in rows[0] if c != "url"]
    con.execute("CREATE OR REPLACE TEMP TABLE _staging AS SELECT unnest($rows, max_depth := 2)",
                {"rows": rows})
    con.execute(f"""UPDATE jobs SET {", ".join(f"{c} = s.{c}" for c in columns)}
                    FROM _staging s WHERE jobs.url = s.url""")
    con.execute("DROP TABLE _staging")


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


def totals(con) -> tuple[int, int]:
    """(offres actives, offres vues au total)."""
    return con.execute("SELECT count(*) FILTER (active), count(*) FROM jobs").fetchone()


def counts(con, facet: str, limit: int | None = 20) -> list[tuple[str, int]]:
    """Nombre d'offres actives par valeur d'une facette, du plus fréquent au plus rare."""
    if facet not in FACETS:
        raise ValueError(f"facette inconnue : {facet}")
    return con.execute(
        f"""SELECT coalesce({facet}, '(inconnu)') AS value, count(*) AS n
            FROM jobs_view WHERE active GROUP BY ALL ORDER BY n DESC, value LIMIT ?""",
        [limit],
    ).fetchall()


def jobs_for_derivation(con) -> list[tuple[str, str, str, str]]:
    return con.execute("SELECT url, title, location, description FROM jobs").fetchall()


# --- contrôles qualité ----------------------------------------------------------------------

SHORT_DESCRIPTION = 300  # caractères : en dessous, l'annonce est probablement tronquée


def quality(con) -> list[dict]:
    """Par source : nombre d'offres actives et part de chaque anomalie (entre 0 et 1).

    Une part élevée sur UNE source signale en général un parseur cassé (l'ATS a changé
    son format), pas un problème du marché.
    """
    cursor = con.execute(
        """SELECT source,
                  count(*)                                               AS active,
                  avg((coalesce(description, '') = '')::INT)             AS empty_description,
                  avg((coalesce(length(description), 0) < ?)::INT)       AS short_description,
                  avg((posted_at IS NULL)::INT)                          AS no_date,
                  avg((canton IS NULL)::INT)                             AS no_canton,
                  avg((coalesce(language, 'other') = 'other')::INT)      AS other_language
           FROM jobs WHERE active GROUP BY source ORDER BY source""",
        [SHORT_DESCRIPTION],
    )
    names = [d[0] for d in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def failing_companies(con) -> list[tuple[str, str, str, str | None]]:
    """Entreprises dont la DERNIÈRE collecte a échoué ou semble suspecte.

    (entreprise, ats, statut, message), triées par entreprise.
    """
    return con.execute(
        """SELECT company, ats, status, error FROM crawl_runs
           WHERE status <> 'skipped'
           QUALIFY row_number() OVER (PARTITION BY company ORDER BY started_at DESC) = 1
                   AND status IN ('error', 'suspect')
           ORDER BY company"""
    ).fetchall()
