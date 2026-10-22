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
from dataclasses import dataclass, field
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


def enrich(job: Job) -> dict:
    """Job → ligne de la table jobs, avec les colonnes dérivées (langue, canton, classes)."""
    c = classify(job.title)
    return {
        **job.model_dump(mode="json", exclude={"language"}),
        "language": job.language or detect_language(job.description),
        "canton": canton_of(job.location),
        "family": c.family,
        "family_keyword": c.family_keyword,
        "seniority": c.seniority,
        "workload_min": c.workload_min,
        "workload_max": c.workload_max,
    }


def ingest(con, payload: dict, seen_at: datetime) -> int:
    """Charge un payload brut en base. Rejouable : c'est ce qui rend le bronze utile."""
    jobs = dedupe(REGISTRY[payload["ats"]].parse(payload))
    storage.upsert_jobs(con, [enrich(j) for j in jobs], seen_at)
    return len(jobs)


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", normalize(name)).strip("-")


def save_raw(payload: dict, raw_dir: Path, day: str) -> Path:
    path = raw_dir / day / f"{payload['ats']}__{_slug(payload['company'])}.json.gz"
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    return path


@dataclass
class CrawlReport:
    ok: list[tuple[str, int, int]] = field(default_factory=list)  # (entreprise, chargées, expirées)
    errors: list[tuple[str, str]] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)


def crawl(con, companies: list[dict], client: PoliteClient, raw_dir: Path = RAW_DIR,
          only: set[str] | None = None) -> CrawlReport:
    started = datetime.now(UTC).replace(tzinfo=None)
    day = started.date().isoformat()
    storage.upsert_companies(con, companies)
    report = CrawlReport()
    for company in companies:
        name, ats, board = company["company"], company["ats"], company["board"]
        if only and normalize(name) not in only:
            continue
        reason = (None if ats in REGISTRY and board
                  else f"pas de connecteur « {ats} »" if ats and ats not in REGISTRY
                  else "ATS ou board inconnu")
        if reason:
            report.skipped.append((name, reason))
            storage.log_run(con, started_at=started, company=name, ats=ats, status="skipped",
                            error=reason)
            continue
        try:
            log.info("collecte %s (%s)", name, ats)
            payload = REGISTRY[ats].fetch(board, name, client, keep=is_target)
            save_raw(payload, raw_dir, day)
            loaded = ingest(con, payload, started)
            expired = storage.expire_missing(con, name, ats, started)
        except Exception as exc:  # une entreprise en échec ne doit pas arrêter les autres
            log.exception("échec %s", name)
            report.errors.append((name, f"{type(exc).__name__}: {exc}"))
            storage.log_run(con, started_at=started, company=name, ats=ats, status="error",
                            error=f"{type(exc).__name__}: {exc}"[:500])
            continue
        company["verified"] = True
        report.ok.append((name, loaded, expired))
        storage.log_run(con, started_at=started, company=name, ats=ats, status="ok",
                        fetched=len(payload["postings"]), loaded=loaded)
    return report


def replay(con, raw_dir: Path = RAW_DIR) -> int:
    """Reconstruit la base à partir de toutes les réponses brutes archivées, dans l'ordre."""
    total = 0
    for path in sorted(raw_dir.glob("*/*.json.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            payload = json.load(f)
        seen_at = datetime.fromisoformat(payload["fetched_at"]).replace(tzinfo=None)
        total += ingest(con, payload, seen_at)
    return total


def reclassify(con) -> int:
    """Recalcule familles, séniorité et taux pour toutes les offres (après un changement de
    règles), sans rien re-télécharger : les colonnes dérivées se recalculent à volonté."""
    rows = []
    for url, title in storage.all_titles(con):
        c = classify(title)
        rows.append({"url": url, "family": c.family, "family_keyword": c.family_keyword,
                     "seniority": c.seniority, "workload_min": c.workload_min,
                     "workload_max": c.workload_max})
    storage.update_classification(con, rows)
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
