"""API de recommandation (M8) : le moteur BM25 derrière HTTP, pour l'app DoxAI.

    GET  /health     → {"status": "ok"}           (le conteneur répond)
    GET  /status     → offres indexées, date de chargement de la base
    POST /recommend  {"cv_text": "...", "k": 10, "cantons": ["GE", "VD"]}
                     → [{"job_id", "title", "company", "url", …, "score"}], score décroissant

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
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import duckdb
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field, StringConstraints

from job_rec_ai import storage
from job_rec_ai.bm25 import BM25
from job_rec_ai.recommend import document, rank

log = logging.getLogger("job_rec_ai.api")
REFRESH = 300  # secondes entre deux vérifications du fichier de la base


class Index:
    """Les offres actives et leur index BM25, rechargés quand la base change."""

    def __init__(self, path: Path):
        self.path = path
        self.jobs: list[dict] = []
        self.bm25: BM25 | None = None
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
                    jobs = storage.jobs_for_ranking(con)
            except duckdb.Error as e:  # verrouillée par la collecte : on garde l'ancien index
                log.warning("base illisible pour l'instant (%s) : index précédent gardé", e)
                return
            self.jobs, self.bm25 = jobs, BM25([document(j) for j in jobs])
            self.mtime, self.loaded_at = mtime, datetime.now(UTC)
            log.info("index rechargé : %d offres", len(jobs))


CvText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50_000)]


class RecommendRequest(BaseModel):
    cv_text: CvText = Field(description="Texte du CV ou du profil (jamais conservé)")
    k: int = Field(10, ge=1, le=50, description="Nombre d'offres à renvoyer")
    cantons: list[str] | None = Field(None, description="Filtre dur, ex. [\"GE\"]")


class Recommendation(BaseModel):
    job_id: str  # l'URL de l'offre : la clé stable de la base
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

    return app


app = create_app()
