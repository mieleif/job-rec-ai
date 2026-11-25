"""API de recommandation (M8) : le moteur hybride (BM25 + vecteurs) derrière HTTP, pour DoxAI.

    GET  /health     → {"status": "ok"}           (le conteneur répond)
    GET  /status     → offres indexées, date de chargement de la base
    POST /recommend  {"cv_text": "...", "k": 10, "cantons": ["GE", "VD"],
                      "families": ["Data & IA"]}
                     → [{"job_id", "id", "title", "company", "url", …, "score"}], score décroissant
    GET  /jobs       ?q=&cantons=GE,VD&families=Data%20%26%20IA,…&workload_min=&workload_max=
                     &posted_within_days=&page=1&per_page=20&sort=recent|relevance
                     → {"total", "page", "per_page", "companies", "jobs": [JobSummary], "facets"}
    GET  /families   → {"families": [...]}  les familles de métier (families.FAMILIES)
    POST /classify   {"titles": ["Comptable", …]} → {"families": [...]} (règles, sans modèle)
    GET  /jobs/{id}  → JobDetail (l'annonce en Markdown, structure gardée) ; 404 sinon
    GET  /jobs/{id}/similar?k=4 → [JobSummary], les offres les plus proches de celle-ci

Les routes /jobs servent les pages publiques d'offres de DoxAI (liste et page par offre) ;
contrat détaillé dans docs/integration-doxai.md. `id` = 16 caractères hexadécimaux du
SHA-256 de l'URL de l'offre (catalog.job_id), stable d'une collecte à l'autre. Chaque offre
porte `company_domain` (« vitol.com »), lu dans la table company_domains : l'API ne cherche
jamais un domaine elle-même (voir domains.py).

Le service tourne sur le réseau Docker du VPS, sans URL publique : seuls les conteneurs de
DoxAI l'appellent. Un jeton (JOB_REC_TOKEN) peut quand même être exigé, par précaution.

/recommend est HYBRIDE (recommend.hybrid_rank) si trois conditions sont réunies : un jeton
INFOMANIAK_API_TOKEN, des vecteurs pour au moins 90 % des offres (`job-rec-ai embed`, après la
collecte) et une réponse de l'API d'embeddings en moins de 4 s. Sinon, BM25 seul : jamais
d'erreur à cause d'un tiers. GET /status dit lequel sert (`ranking`). JOB_REC_RERANK=1 ajoute
le reranker Qwen3 (~0,6 s) sur les 60 premières offres ; éteint par défaut.

Les offres sont chargées en mémoire au démarrage. La collecte nocturne écrit la base dans un
AUTRE processus : DuckDB n'admet pas de lecteur pendant qu'un autre processus écrit. Le
rechargement est donc opportuniste : au plus toutes les REFRESH secondes, si la base ou le
cache des vecteurs a changé ; si la base est verrouillée (collecte en cours), on garde l'index
précédent et on réessaiera.

Le texte du CV n'est jamais journalisé ni conservé, son vecteur non plus. En hybride, il part
chez Infomaniak (hébergement suisse) sans ses lignes de coordonnées.
"""

import logging
import os
import sqlite3
import threading
import time
from collections import Counter
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated, Literal

import duckdb
import numpy as np
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field, StringConstraints

from job_rec_ai import catalog, embeddings, storage
from job_rec_ai.bm25 import BM25
from job_rec_ai.cv import for_api
from job_rec_ai.families import FAMILIES, families_of_titles
from job_rec_ai.recommend import (
    EMBEDDER,
    MAX_QUERY_CHARS,
    RERANKER,
    TRUNCATION,
    Vectors,
    document,
    hybrid_rank,
    passage,
    rank,
)
from job_rec_ai.rerank import CANDIDATES

log = logging.getLogger("job_rec_ai.api")
REFRESH = 300  # secondes entre deux vérifications du fichier de la base
# Ce qu'un tiers peut faire échouer : appel refusé ou trop lent, plafond atteint, réponse mal
# formée, disque plein pour le journal. Pas `Exception` : une erreur du code doit se voir.
OUTSIDE = (embeddings.ApiError, embeddings.BudgetExceeded, LookupError, TypeError, ValueError,
           OSError)


@dataclass(frozen=True)
class Snapshot:
    jobs: list[dict]
    by_id: dict[str, int]
    bm25: BM25
    search_bm25: BM25
    vectors: Vectors | None  # None : pas de jeton, ou cache de vecteurs absent ou illisible

    @property
    def hybrid(self) -> bool:
        return self.vectors is not None and self.vectors.usable


class Index:
    """Les offres actives et leurs index BM25, rechargés quand la base change.

    `bm25` (titre + description) est celui de /recommend et des offres semblables ;
    `search_bm25` (titre + entreprise + description) celui de GET /jobs?q=. Deux index
    plutôt qu'un : /recommend garde exactement son classement. `vectors_path` : le cache des
    vecteurs, à charger aussi (None : BM25 seul)."""

    def __init__(self, path: Path, vectors_path: Path | None = None):
        self.path = path
        self.vectors_path = vectors_path
        self.jobs: list[dict] = []
        self.by_id: dict[str, int] = {}  # id → position dans jobs : GET /jobs/{id} en O(1)
        self.bm25: BM25 | None = None
        self.search_bm25: BM25 | None = None
        self.snapshot: Snapshot | None = None  # ce que lisent les routes /jobs
        self.mtime: float | None = None
        self.vectors_mtime: float | None = None
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
            vectors_mtime = self._vectors_mtime()
            if mtime == self.mtime:
                # `embed` écrit les vecteurs après la collecte : mêmes offres, vecteurs neufs
                if vectors_mtime != self.vectors_mtime and self.snapshot:
                    self.snapshot = replace(self.snapshot, vectors=self._vectors(self.jobs))
                    self.vectors_mtime = vectors_mtime
                return
            try:
                with duckdb.connect(str(self.path), read_only=True) as con:
                    domains = storage.company_domains(con)
                    jobs = [catalog.prepare(j, domains) for j in storage.jobs_for_api(con)]
            except duckdb.Error as e:  # verrouillée par la collecte : on garde l'ancien index
                log.warning("base illisible pour l'instant (%s) : index précédent gardé", e)
                return
            self.jobs, self.bm25 = jobs, BM25([document(j) for j in jobs])
            self.search_bm25 = BM25([catalog.search_document(j) for j in jobs])
            self.by_id = {j["id"]: i for i, j in enumerate(jobs)}
            # Une seule affectation : une requête servie pendant un rechargement (autre
            # thread) lit tout de la même génération, jamais un id neuf sur l'ancienne liste
            self.snapshot = Snapshot(self.jobs, self.by_id, self.bm25, self.search_bm25,
                                     self._vectors(jobs))
            self.mtime, self.loaded_at = mtime, datetime.now(UTC)
            self.vectors_mtime = vectors_mtime
            log.info("index rechargé : %d offres", len(jobs))

    def _vectors_mtime(self) -> float | None:
        try:
            return self.vectors_path.stat().st_mtime if self.vectors_path else None
        except FileNotFoundError:
            return None

    def _vectors(self, jobs: list[dict]) -> Vectors | None:
        if self._vectors_mtime() is None:
            return None
        try:
            vectors = Vectors.load(self.vectors_path, jobs)
        except (sqlite3.Error, ValueError) as e:  # cache verrouillé, abîmé ou d'un autre modèle
            log.warning("vecteurs illisibles (%s) : BM25 seul", type(e).__name__)
            return None
        log.info("vecteurs : %d offres sur %d", vectors.count, len(jobs))
        return vectors


CvText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50_000)]


class RecommendRequest(BaseModel):
    cv_text: CvText = Field(description="Texte du CV ou du profil (jamais conservé)")
    k: int = Field(10, ge=1, le=50, description="Nombre d'offres à renvoyer")
    cantons: list[str] | None = Field(None, description="Filtre dur, ex. [\"GE\"]")
    families: list[str] | None = Field(
        None, description="Filtre dur sur la famille exacte (OU), ex. [\"Data & IA\"]")


class Recommendation(BaseModel):
    job_id: str  # l'URL de l'offre : la clé stable de la base
    id: str      # l'identifiant des routes /jobs (catalog.job_id)
    title: str
    company: str
    company_domain: str | None  # « vitol.com » : pour le logo (voir domains.py) ; None : inconnu
    url: str
    location: str          # « Genève » ; vide : inconnu
    canton: str | None
    family: str | None
    seniority: str | None
    workload_min: int | None
    workload_max: int | None
    posted_at: str | None
    publisher_type: str | None
    snippet: str           # ≤ 240 caractères de texte brut, comme sur /jobs
    score: float


class JobSummary(BaseModel):
    id: str
    url: str
    title: str
    company: str
    company_domain: str | None  # domaine nu de l'employeur (« coop.ch »), None si inconnu
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
    cantons: dict[str, int]   # tous les filtres appliqués sauf `cantons`
    families: dict[str, int]  # tous les filtres appliqués sauf `families` (« Autre » compris)


class JobList(BaseModel):
    total: int
    page: int
    per_page: int
    companies: int  # employeurs distincts parmi les `total` résultats
    jobs: list[JobSummary]
    facets: Facets


Title = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]


class ClassifyRequest(BaseModel):
    titles: list[Title] = Field(max_length=20, description="Intitulés de poste (ceux d'un CV)")


class FamilyList(BaseModel):
    families: list[str]


def _labels(value: str | None) -> frozenset[str]:
    """Les valeurs d'un paramètre à virgules (« GE, vd » → {"GE", "vd"}), sans espaces de
    bord ni valeurs vides, casse gardée : les familles sont comparées telles quelles."""
    return frozenset(v.strip() for v in (value or "").split(",") if v.strip())


def api_text(cv_text: str) -> str:
    """Le texte qui part chez Infomaniak : sans coordonnées, et pas plus que l'API n'accepte."""
    return for_api(cv_text)[:MAX_QUERY_CHARS]


def create_app(db_path: Path | str | None = None) -> FastAPI:
    path = Path(db_path or os.environ.get("JOB_REC_DB", storage.DEFAULT_DB))
    token = os.environ.get("JOB_REC_TOKEN")
    reranking = os.environ.get("JOB_REC_RERANK") == "1"
    folder = path.parent / "embeddings"
    infomaniak = embeddings.Client.online(folder / embeddings.USAGE.name)
    fallbacks = Counter()  # replis sur BM25 ou sur l'ordre hybride, depuis le démarrage
    index = Index(path, folder / embeddings.CACHE.name if infomaniak else None)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        index.refresh(force=True)
        yield
        if infomaniak:
            infomaniak.close()

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
                "loaded_at": index.loaded_at.isoformat() if index.loaded_at else None,
                "ranking": "hybrid" if index.snapshot and index.snapshot.hybrid else "bm25",
                "vectors": index.snapshot.vectors.count
                if index.snapshot and index.snapshot.vectors else 0,
                "fallbacks": fallbacks.total()}

    def ranked(current: Snapshot, cv_text: str) -> tuple[list[dict], str]:
        """(offres classées, classement servi). Une panne du tiers n'est citée que par son
        type : son message pourrait reprendre le CV."""
        if current.hybrid:
            try:
                query, _ = infomaniak.embed_query(EMBEDDER, api_text(cv_text))
                if query.shape != (EMBEDDER.dim,) or not np.isfinite(query).all():
                    raise ValueError("vecteur invalide")
            except OUTSIDE as e:
                fallbacks["embedding"] += 1
                log.warning("embedding indisponible (%s) : BM25 seul", type(e).__name__)
            else:
                return (hybrid_rank(current.jobs, cv_text, query, current.vectors, current.bm25),
                        "hybrid")
        return [j for j in rank(current.jobs, cv_text, index=current.bm25)
                if j["score"] > 0], "bm25"

    def reranked(hits: list[dict], cv_text: str) -> list[dict]:
        """Les CANDIDATES premières offres relues par le cross-encoder, APRÈS les filtres."""
        head = hits[:CANDIDATES]
        try:
            scores, _ = infomaniak.rerank(RERANKER, api_text(cv_text),
                                          [passage(j) for j in head], TRUNCATION)
        except OUTSIDE as e:
            fallbacks["rerank"] += 1
            log.warning("reranker indisponible (%s) : ordre hybride gardé", type(e).__name__)
            return hits
        order = np.argsort(-scores, kind="stable")
        return [{**head[i], "score": float(scores[i])} for i in order]

    @app.post("/recommend", dependencies=[Depends(authorized)])
    def recommend(req: RecommendRequest) -> list[Recommendation]:
        started = time.perf_counter()
        current = ready()
        jobs, ranking = ranked(current, req.cv_text)
        wanted = {c.upper() for c in req.cantons} if req.cantons else None
        families = {f.strip() for f in req.families} if req.families else None
        hits = [j for j in jobs if (wanted is None or j["canton"] in wanted)
                and (families is None or j["family"] in families)]
        if ranking == "hybrid" and reranking and hits:
            hits, ranking = reranked(hits, req.cv_text), "hybrid+rerank"
        hits = hits[:req.k]
        log.info("recommend %s k=%d cantons=%s families=%s → %d offres en %.0f ms", ranking,
                 req.k, req.cantons, req.families, len(hits),
                 1000 * (time.perf_counter() - started))
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
        families: Annotated[str | None, Query(
            max_length=1000, description="libellés exacts, virgules : Data & IA,Santé & Soins")
        ] = None,
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
            q=q, cantons=frozenset(c.upper() for c in _labels(cantons)),
            families=_labels(families),
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

    @app.get("/families", dependencies=[Depends(authorized)])
    def families_list() -> FamilyList:
        """Les familles de métier, dans l'ordre des règles : la liste de référence de DoxAI."""
        return FamilyList(families=list(FAMILIES))

    @app.post("/classify", dependencies=[Depends(authorized)])
    def classify_titles(req: ClassifyRequest) -> FamilyList:
        """Les familles d'une liste d'intitulés (la plus fréquente d'abord, « Autre » écarté),
        par les mêmes règles que la collecte. Ni la base ni un modèle : les titres ne sont
        pas journalisés."""
        return FamilyList(families=families_of_titles(req.titles))

    return app


app = create_app()
