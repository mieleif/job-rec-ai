"""Le parcours d'une offre : ATS → JSON brut (bronze) → Job → enrichi → DuckDB (silver).

    fetch ──► data/raw/<date>/<ats>__<entreprise>.json.gz   (on garde TOUT, tel quel)
          └─► parse ─► enrich ─► dedupe ─► upsert ─► expire

Chaque entreprise est traitée isolément : si l'ATS de Rolex plante, Nestlé est quand même
collectée, et les offres de Rolex ne sont PAS expirées (une panne ne prouve rien).
"""

import gzip
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from job_rec_ai import storage
from job_rec_ai.connectors import REGISTRY
from job_rec_ai.dedupe import dedupe
from job_rec_ai.families import classify
from job_rec_ai.geo import canton_of, is_target
from job_rec_ai.http import PoliteClient
from job_rec_ai.models import Job
from job_rec_ai.text import detect_language, normalize

log = logging.getLogger(__name__)
RAW_DIR = Path("data/raw")


def derive(title: str, location: str, description: str) -> dict:
    """Les colonnes dérivées d'une offre : recalculables à volonté, sans re-télécharger."""
    return {
        "language": detect_language(description),
        "canton": canton_of(location),
        **asdict(classify(title)),
    }


def enrich(job: Job) -> dict:
    """Job → ligne de la table jobs (champs du Job + colonnes dérivées)."""
    row = {**job.model_dump(mode="json"), **derive(job.title, job.location, job.description)}
    row["language"] = job.language or row["language"]  # la langue déclarée par l'ATS prime
    return row


def ingest(con, payload: dict) -> tuple[int, int]:
    """Charge le payload brut d'UNE entreprise : upsert puis expiration de ses offres
    absentes. Un payload est un instantané complet de l'entreprise à `fetched_at` : c'est
    ce qui rend le bronze rejouable. Renvoie (offres chargées, offres expirées)."""
    seen_at = datetime.fromisoformat(payload["fetched_at"]).replace(tzinfo=None)
    jobs = dedupe(REGISTRY[payload["ats"]].parse(payload))
    storage.upsert_jobs(con, [enrich(j) for j in jobs], seen_at)
    expired = storage.expire_missing(con, payload["company"], payload["ats"], seen_at)
    return len(jobs), expired


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", normalize(name)).strip("-")


def save_raw(payload: dict, raw_dir: Path) -> Path:
    day = payload["fetched_at"][:10]
    path = raw_dir / day / f"{payload['ats']}__{_slug(payload['company'])}.json.gz"
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    return path


def skip_reason(company: dict) -> str | None:
    """Pourquoi on ne peut pas collecter cette entreprise (None : on peut)."""
    if company["ats"] and company["ats"] not in REGISTRY:
        return f"pas de connecteur « {company['ats']} »"
    if not company["ats"] or not company["board"]:
        return "ATS ou board inconnu"
    return None


def fetch_company(company: dict, client: PoliteClient) -> dict:
    """Rapporte le payload brut d'une entreprise, limité à l'arc lémanique."""
    return REGISTRY[company["ats"]].fetch(company["board"], company["company"], client,
                                          keep=is_target)


@dataclass
class CrawlReport:
    ok: list[tuple[str, int, int]] = field(default_factory=list)  # (entreprise, chargées, expirées)
    errors: list[tuple[str, str]] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)


def crawl(con, companies: list[dict], client: PoliteClient, raw_dir: Path = RAW_DIR,
          only: list[str] | None = None) -> CrawlReport:
    started = datetime.now(UTC).replace(tzinfo=None)
    wanted = {normalize(n) for n in only} if only else None
    storage.upsert_companies(con, companies)
    report = CrawlReport()
    for company in companies:
        name, ats = company["company"], company["ats"]
        if wanted and normalize(name) not in wanted:
            continue
        reason = skip_reason(company)
        if reason:
            report.skipped.append((name, reason))
            storage.log_run(con, started_at=started, company=name, ats=ats, status="skipped",
                            error=reason)
            continue
        try:
            log.info("collecte %s (%s)", name, ats)
            payload = fetch_company(company, client)
            save_raw(payload, raw_dir)
            loaded, expired = ingest(con, payload)
        except Exception as exc:  # une entreprise en échec ne doit pas arrêter les autres
            log.exception("échec %s", name)
            error = f"{type(exc).__name__}: {exc}"
            report.errors.append((name, error))
            storage.log_run(con, started_at=started, company=name, ats=ats, status="error",
                            error=error[:500])
            continue
        report.ok.append((name, loaded, expired))
        storage.log_run(con, started_at=started, company=name, ats=ats, status="ok",
                        fetched=len(payload["postings"]), loaded=loaded)
    return report


def replay(con, raw_dir: Path = RAW_DIR) -> int:
    """Reconstruit la base à partir de toutes les réponses brutes archivées, dans l'ordre."""
    total = 0
    for path in sorted(raw_dir.glob("*/*.json.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            total += ingest(con, json.load(f))[0]
    return total


def rederive(con) -> int:
    """Recalcule langue, canton, famille, séniorité et taux pour toutes les offres (après
    un changement de règles), sans rien re-télécharger."""
    rows = [{"url": url, **derive(title, location, description)}
            for url, title, location, description in storage.jobs_for_derivation(con)]
    storage.update_derived(con, rows)
    return len(rows)


@dataclass
class SnapshotDiff:
    new: list[Job]
    updated: list[Job]
    expired: list[Job]


def diff_snapshots(old: list[Job], new: list[Job]) -> SnapshotDiff:
    """Compare deux collectes. Clé = URL ; « modifiée » = titre ou description changés."""
    before = {str(j.url): j for j in old}
    after = {str(j.url): j for j in new}
    return SnapshotDiff(
        new=[j for url, j in after.items() if url not in before],
        updated=[j for url, j in after.items() if url in before
                 and (j.title, j.description) != (before[url].title, before[url].description)],
        expired=[j for url, j in before.items() if url not in after],
    )
