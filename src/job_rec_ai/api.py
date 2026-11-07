"""API de recommandation (M8) : le moteur BM25 derrière HTTP, pour l'app DoxAI.

    GET  /health     → {"status": "ok"}           (le conteneur répond)
    GET  /status     → offres indexées, date de chargement de la base
    POST /recommend  {"cv_text": "...", "k": 10, "cantons": ["GE", "VD"]}
                     → [{"job_id", "id", "title", "company", "url", …, "score"}], score décroissant
    GET  /jobs       ?q=&cantons=GE,VD&workload_min=&workload_max=&posted_within_days=
                     &page=1&per_page=20&sort=recent|relevance
                     → {"total", "page", "per_page", "jobs": [JobSummary], "facets"}
    GET  /jobs/{id}  → JobDetail (l'annonce en Markdown, structure gardée) ; 404 sinon
    GET  /jobs/{id}/similar?k=4 → [JobSummary], les offres les plus proches de celle-ci

Les routes /jobs servent les pages publiques d'offres de DoxAI (liste et page par offre) ;
contrat détaillé dans docs/integration-doxai.md. `id` = 16 caractères hexadécimaux du
SHA-256 de l'URL de l'offre (catalog.job_id), stable d'une collecte à l'autre.

Le service tourne sur le réseau Docker du VPS, sans URL publique : seuls les conteneurs de
DoxAI l'appellent. Un jeton (JOB_REC_TOKEN) peut quand même être exigé, par précaution.

Les offres sont chargées en mémoire au démarrage (BM25 sur ~1 700 offres : quelques
millisecondes par requête). La collecte nocturne écrit la base dans un AUTRE processus :
DuckDB n'admet pas de lecteur pendant qu'un autre processus écrit. Le rechargement est donc
opportuniste : au plus toutes les REFRESH secondes, si le fichier a changé ; si la base est
verrouillée (collecte en cours), on garde l'index précédent et on réessaiera.

Le texte du CV n'est jamais journalisé ni conservé.
"""

import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated, Literal

import duckdb
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field, StringConstraints

from job_rec_ai import catalog, storage
from job_rec_ai.bm25 import BM25
from job_rec_ai.recommend import document, rank

log = logging.getLogger("job_rec_ai.api")
REFRESH = 300  # secondes entre deux vérifications du fichier de la base


@dataclass(frozen=True)
class Snapshot:
    jobs: list[dict]
    by_id: dict[str, int]
    bm25: BM25
    search_bm25: BM25


class Index:
    """Les offres actives et leurs index BM25, rechargés quand la base change.

    `bm25` (titre + description) est celui de /recommend et des offres semblables ;
    `search_bm25` (titre + entreprise + description) celui de GET /jobs?q=. Deux index
    plutôt qu'un : /recommend garde exactement son classement."""

    def __init__(self, path: Path):
        self.path = path
        self.jobs: list[dict] = []
        self.by_id: dict[str, int] = {}  # id → position dans jobs : GET /jobs/{id} en O(1)
        self.bm25: BM25 | None = None
        self.search_bm25: BM25 | None = None
        self.snapshot: Snapshot | None = None  # ce que lisent les routes /jobs
        self.mtime: float | None = None
        self.loaded_at: datetime | None = None
        self.checked = 0.0
        self.lock = threading.Lock()

    def refresh(self, force: bool = False) -> None:
        if not force and time.monotonic() - self.checked < REFRESH:
            return
        with self.lock:
            self.checked = time.monotonic()
            try:
                mtime = self.path.stat().st_mtime
            except FileNotFoundError:
                log.warning("base introuvable : %s", self.path)
                return
            if mtime == self.mtime:
                return
            try:
                with duckdb.connect(str(self.path), read_only=True) as con:
                    jobs = [catalog.prepare(j) for j in storage.jobs_for_api(con)]
            except duckdb.Error as e:  # verrouillée par la collecte : on garde l'ancien index
                log.warning("base illisible pour l'instant (%s) : index précédent gardé", e)
                return
            self.jobs, self.bm25 = jobs, BM25([document(j) for j in jobs])
            self.search_bm25 = BM25([catalog.search_document(j) for j in jobs])
            self.by_id = {j["id"]: i for i, j in enumerate(jobs)}
            # Une seule affectation : une requête servie pendant un rechargement (autre
            # thread) lit tout de la même génération, jamais un id neuf sur l'ancienne liste
            self.snapshot = Snapshot(self.jobs, self.by_id, self.bm25, self.search_bm25)
            self.mtime, self.loaded_at = mtime, datetime.now(UTC)
            log.info("index rechargé : %d offres", len(jobs))


CvText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50_000)]


class RecommendRequest(BaseModel):
    cv_text: CvText = Field(description="Texte du CV ou du profil (jamais conservé)")
    k: int = Field(10, ge=1, le=50, description="Nombre d'offres à renvoyer")
    cantons: list[str] | None = Field(None, description="Filtre dur, ex. [\"GE\"]")


class Recommendation(BaseModel):
    job_id: str  # l'URL de l'offre : la clé stable de la base
    id: str      # l'identifiant des routes /jobs (catalog.job_id)
    title: str
    company: str
    url: str
    canton: str | None
    family: str | None
    seniority: str | None
    workload_min: int | None
    workload_max: int | None
    posted_at: str | None
    publisher_type: str | None
    score: float


class JobSummary(BaseModel):
    id: str
    url: str
    title: str
    company: str
    location: str
    canton: str | None
    workload_min: int | None
    workload_max: int | None
    posted_at: str | None  # AAAA-MM-JJ
    language: str | None   # fr | de | en | it
    employment_type: str | None
    family: str | None
    snippet: str           # ≤ 240 caractères de texte brut


class JobDetail(JobSummary):
    description_markdown: str  # l'annonce structurée (##/###, listes, gras, liens http(s))
    description_text: str      # le texte brut sur une ligne, celui que lit le moteur
    category: str | None
    seniority: str | None
    source: str | None


class Facets(BaseModel):
    cantons: dict[str, int]  # tous les filtres appliqués sauf `cantons`


class JobList(BaseModel):
    total: int
    page: int
    per_page: int
    jobs: list[JobSummary]
    facets: Facets


def create_app(db_path: Path | str | None = None) -> FastAPI:
    path = Path(db_path or os.environ.get("JOB_REC_DB", storage.DEFAULT_DB))
    token = os.environ.get("JOB_REC_TOKEN")
    index = Index(path)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        index.refresh(force=True)
        yield

    app = FastAPI(title="job-rec-ai", version="0.1.0", lifespan=lifespan)

    def authorized(authorization: str | None = Header(None)) -> None:
        if token and authorization != f"Bearer {token}":
            raise HTTPException(401, "jeton manquant ou invalide")

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/status", dependencies=[Depends(authorized)])
    def status() -> dict:
        index.refresh()  # sinon il montre l'index d'avant la collecte jusqu'au prochain /recommend
        return {"offers": len(index.jobs),
                "loaded_at": index.loaded_at.isoformat() if index.loaded_at else None}

    @app.post("/recommend", dependencies=[Depends(authorized)])
    def recommend(req: RecommendRequest) -> list[Recommendation]:
        started = time.perf_counter()
        index.refresh()
        if index.bm25 is None:
            raise HTTPException(503, "index indisponible (base absente ou en cours d'écriture)")
        ranked = rank(index.jobs, req.cv_text, index=index.bm25)
        wanted = {c.upper() for c in req.cantons} if req.cantons else None
        hits = [j for j in ranked
                if j["score"] > 0 and (wanted is None or j["canton"] in wanted)][:req.k]
        log.info("recommend k=%d cantons=%s → %d offres en %.0f ms", req.k, req.cantons,
                 len(hits), 1000 * (time.perf_counter() - started))
        return [Recommendation(job_id=j["url"], **{f: j.get(f) for f in Recommendation.model_fields
                                                   if f != "job_id"}) for j in hits]

    def ready() -> Snapshot:
        index.refresh()
        current = index.snapshot
        if current is None:
            raise HTTPException(503, "index indisponible (base absente ou en cours d'écriture)")
        return current

    def position(current: Snapshot, job_id: str) -> int:
        found = current.by_id.get(job_id) if catalog.ID_PATTERN.match(job_id) else None
        if found is None:
            raise HTTPException(404, "not_found")
        return found

    @app.get("/jobs", dependencies=[Depends(authorized)])
    def jobs(
        q: Annotated[str | None, Query(max_length=500)] = None,
        cantons: Annotated[str | None, Query(max_length=200, description="ex. GE,VD")] = None,
        workload_min: Annotated[int | None, Query(ge=0, le=100)] = None,
        workload_max: Annotated[int | None, Query(ge=0, le=100)] = None,
        posted_within_days: Annotated[int | None, Query(ge=0, le=3650)] = None,
        page: Annotated[int, Query(ge=1, le=10_000)] = 1,
        per_page: Annotated[int, Query(ge=1, le=50)] = 20,
        sort: Annotated[Literal["recent", "relevance"] | None, Query()] = None,
    ) -> JobList:
        if workload_min is not None and workload_max is not None and workload_min > workload_max:
            raise HTTPException(422, "workload_min > workload_max")
        current = ready()
        query = catalog.Query(
            q=q, cantons=frozenset(c.strip().upper() for c in (cantons or "").split(",")
                                   if c.strip()),
            workload_min=workload_min, workload_max=workload_max,
            posted_within_days=posted_within_days, sort=sort, page=page, per_page=per_page)
        return JobList(**catalog.search(current.jobs, current.search_bm25, query, date.today()))

    @app.get("/jobs/{job_id}", dependencies=[Depends(authorized)])
    def job(job_id: str) -> JobDetail:
        current = ready()
        return JobDetail(**catalog.detail(current.jobs[position(current, job_id)]))

    @app.get("/jobs/{job_id}/similar", dependencies=[Depends(authorized)])
    def similar(job_id: str, k: Annotated[int, Query(ge=1, le=12)] = 4) -> list[JobSummary]:
        current = ready()
        return [JobSummary(**s) for s in catalog.similar(current.jobs, current.bm25,
                                                         position(current, job_id), k)]

    return app


app = create_app()
