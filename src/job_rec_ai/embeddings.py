"""Client de l'API Infomaniak (embeddings et reranking), cache des vecteurs, budget.

Un embedding projette un texte en un point d'un espace à 384-4096 dimensions, où la distance
encode le SENS : « IA », « AI » et « intelligence artificielle » tombent au même endroit sans
mot commun. Le modèle est un bi-encoder : CV et offres sont encodés séparément, donc les
offres le sont une fois pour toutes et chercher revient à un produit matrice × vecteur.

Pourquoi l'API et pas un modèle local : pas de torch (~1 Go) dans l'image du VPS (4 Go
partagés), des modèles de 8 à 9 milliards de paramètres, et un hébergement suisse (nLPD).

Réglages (.env, jamais commité) : INFOMANIAK_API_TOKEN, et INFOMANIAK_PRODUCT_ID (facultatif :
lu sur GET /1/ai s'il n'y a qu'un produit). Prix et faits : docs/infomaniak-modeles.md.

Confidentialité : aucun texte n'est journalisé ni mis en cache, seulement des empreintes
SHA-256, des comptes de tokens et des vecteurs. Les vecteurs et scores d'un CV vont dans
data/private/ (un embedding se laisse en partie inverser : c'est une donnée personnelle).
"""

import hashlib
import json
import logging
import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import httpx
import numpy as np

log = logging.getLogger(__name__)

API = "https://api.infomaniak.com"
CACHE = Path("data/embeddings/infomaniak.sqlite")           # offres (textes publics)
PRIVATE_CACHE = Path("data/private/infomaniak.sqlite")      # tout ce qui dérive d'un CV
USAGE = Path("data/embeddings/usage.jsonl")                 # un appel par ligne : tokens, CHF
BUDGET_CHF = 3.0             # évaluation : plafond total, tous lancements confondus
MONTHLY_BUDGET_CHF = 2.0     # en service (API et `embed`), par mois ; JOB_REC_BUDGET_CHF
ONLINE_TIMEOUT = 4.0         # secondes : au-delà, /recommend répond avec BM25 seul
WARN_AT = 0.8
BATCH = 32
RETRY_STATUSES = {429, 500, 502, 503, 504}
# Majorant volontairement pessimiste pour le contrôle du budget AVANT l'appel (la facture
# exacte vient de `usage` dans la réponse). Français et allemand : ~3,5 caractères/token.
CHARS_PER_TOKEN = 2.5

TASK = "Given a candidate's CV, retrieve job ads that match their skills and experience."


@dataclass(frozen=True)
class Model:
    name: str          # nom exact côté API
    price: float       # CHF par million de tokens en entrée
    dim: int = 0       # 0 pour un reranker
    query: str = "{}"  # gabarit côté requête (les documents sont envoyés nus)
    max_chars: int | None = None  # coupe avant l'envoi, si l'API refuse au lieu de tronquer


# Gabarits de requête : ceux des fiches Hugging Face (modèles « instruction-aware »)
EMBEDDERS = {
    "qwen3-8b": Model("Qwen/Qwen3-Embedding-8B", 0.07, 4096,
                      f"Instruct: {TASK}\nQuery:{{}}"),
    "gemma2": Model("bge_multilingual_gemma2", 0.065, 3584,
                    f"<instruct>{TASK}\n<query>{{}}"),
    # 128 tokens au plus, et un HTTP 413 au-delà : ~2,5 caractères/token (tokenizer anglais)
    "minilm": Model("mini_lm_l12_v2", 0.0, 384, max_chars=320),
}
RERANKERS = {
    "bge-v2-m3": Model("BAAI/bge-reranker-v2-m3", 0.01),
    "qwen3-0.6b": Model("Qwen/Qwen3-Reranker-0.6B", 0.009),
}


class BudgetExceeded(RuntimeError):
    """Le prochain appel ferait dépasser le plafond : on s'arrête avant, pas après."""


class ApiError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


@dataclass
class Call:
    """Ce qu'un appel a coûté ; rejoué tel quel depuis le cache, pour que coût et latence
    d'une évaluation relancée restent ceux du vrai appel."""
    tokens: int = 0
    chf: float = 0.0
    ms: float = 0.0


def sha(*parts) -> str:
    return hashlib.sha256("\x1f".join(map(str, parts)).encode()).hexdigest()


class Ledger:
    """Journal des dépenses (JSONL) et plafond. Persistant : le plafond vaut pour toute la
    tâche, pas pour un seul lancement. `monthly` : le plafond repart à zéro chaque mois (un
    service qui tourne sans fin). Chaque processus ne relit le fichier qu'au démarrage et au
    changement de mois : la collecte et l'API peuvent donc dépasser un peu à elles deux."""

    def __init__(self, path: Path | None = None, budget: float = BUDGET_CHF,
                 monthly: bool = False):
        self.path, self.budget, self.monthly = Path(path or USAGE), budget, monthly
        self._lock = threading.Lock()  # l'API sert plusieurs requêtes à la fois
        self._load()

    @classmethod
    def in_service(cls, path: Path) -> "Ledger":
        return cls(path, float(os.environ.get("JOB_REC_BUDGET_CHF") or MONTHLY_BUDGET_CHF),
                   monthly=True)

    def _load(self) -> None:
        self.spent, self._warned = 0.0, False
        self._month = datetime.now().isoformat()[:7]
        if self.path.exists():
            with self.path.open(encoding="utf-8") as f:
                rows = [json.loads(line) for line in f if line.strip()]
            self.spent = sum(r["chf"] for r in rows
                             if not self.monthly or r["at"].startswith(self._month))

    def check(self, upper_bound_chf: float) -> None:
        with self._lock:
            if self.monthly and datetime.now().isoformat()[:7] != self._month:
                self._load()
        if self.spent + upper_bound_chf > self.budget:
            raise BudgetExceeded(
                f"{self.spent:.3f} CHF dépensés, appel estimé à {upper_bound_chf:.3f} CHF au "
                f"plus, plafond {self.budget:.2f} CHF")

    def record(self, kind: str, model: Model, inputs: int, tokens: int, ms: float) -> Call:
        call = Call(tokens, tokens * model.price / 1e6, ms)
        row = {"at": datetime.now().isoformat(timespec="seconds"), "kind": kind,
               "model": model.name, "inputs": inputs, "tokens": tokens,
               "chf": call.chf, "ms": round(ms)}
        with self._lock:
            self.spent += call.chf
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")
        log.info("%s %s : %d textes, %d tokens, %.6f CHF, %.0f ms (total %.4f CHF)",
                 kind, model.name, inputs, tokens, call.chf, ms, self.spent)
        if self.spent > WARN_AT * self.budget and not self._warned:
            self._warned = True
            log.warning("budget : %.2f CHF sur %.2f", self.spent, self.budget)
        return call


class Store:
    """Cache clé → (valeur, coût d'origine), en SQLite : bibliothèque standard, écriture
    incrémentale (un plantage ne perd que le lot en cours)."""

    def __init__(self, path: Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, value BLOB, "
                        "tokens INTEGER, chf REAL, ms REAL)")

    def get(self, key: str) -> tuple[bytes, Call] | None:
        row = self.db.execute("SELECT value, tokens, chf, ms FROM cache WHERE key = ?",
                              [key]).fetchone()
        return (row[0], Call(*row[1:])) if row else None

    def put(self, rows: list[tuple[str, bytes, Call]]) -> None:
        with self.db:
            self.db.executemany("INSERT OR REPLACE INTO cache VALUES (?, ?, ?, ?, ?)",
                                [(k, v, c.tokens, c.chf, c.ms) for k, v, c in rows])

    def prune(self, keep: set[str]) -> int:
        """Supprime tout sauf `keep` (16 Ko par vecteur : les offres disparues s'accumulent)."""
        gone = [(k,) for (k,) in self.db.execute("SELECT key FROM cache") if k not in keep]
        with self.db:
            self.db.executemany("DELETE FROM cache WHERE key = ?", gone)
        return len(gone)

    def close(self) -> None:
        self.db.close()


def read_vectors(path: Path, model: Model, texts: list[str]) -> tuple[np.ndarray, np.ndarray]:
    """(un vecteur par texte DISTINCT, ligne de chaque texte ou -1), lus dans le cache sans
    appel d'API ni clé. Les textes répétés (titres Coop) partagent une ligne : ~3 300 vecteurs
    au lieu de ~5 200. Lecture seule : une collecte peut écrire le cache en même temps."""
    keys = [sha(model.name, t) for t in texts]
    matrix = np.empty((len(set(keys)), model.dim), dtype=np.float32)
    known: dict[str, int] = {}
    db = sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro", uri=True, timeout=5)
    try:
        for key in dict.fromkeys(keys):
            row = db.execute("SELECT value FROM cache WHERE key = ?", [key]).fetchone()
            if row:
                matrix[len(known)] = np.frombuffer(row[0], np.float32)
                known[key] = len(known)
    finally:
        db.close()
    return matrix[:len(known)], np.array([known.get(k, -1) for k in keys], dtype=int)


class Client:
    """`cache` ou `private_cache` à None : rien n'est écrit sur disque de ce côté-là."""

    def __init__(self, api_key: str, product_id: str | int | None = None, *,
                 ledger: Ledger | None = None, cache: Path | None = CACHE,
                 private_cache: Path | None = PRIVATE_CACHE, max_retries: int = 4,
                 timeout: float = 120, transport: httpx.BaseTransport | None = None,
                 sleep=time.sleep):
        self.ledger = ledger or Ledger()
        self.cache = Store(cache) if cache else None
        self.private = Store(private_cache) if private_cache else None
        self.max_retries, self._sleep = max_retries, sleep
        self._product_id = product_id
        self._http = httpx.Client(base_url=API, timeout=timeout, transport=transport,
                                  headers={"Authorization": f"Bearer {api_key}"})

    @classmethod
    def from_env(cls, **kw) -> "Client | None":
        """None sans clé : l'évaluation se limite alors aux méthodes locales."""
        key = os.environ.get("INFOMANIAK_API_TOKEN")
        return cls(key, os.environ.get("INFOMANIAK_PRODUCT_ID"), **kw) if key else None

    @classmethod
    def online(cls, usage: Path, **kw) -> "Client | None":
        """Pour répondre à une requête : un seul essai, court, et aucun cache sur disque (le
        vecteur du CV d'un utilisateur n'est pas conservé). Utilisable par plusieurs threads."""
        return cls.from_env(ledger=Ledger.in_service(usage), cache=None, private_cache=None,
                            max_retries=0, timeout=ONLINE_TIMEOUT, **kw)

    def close(self) -> None:
        self._http.close()
        for store in (self.cache, self.private):
            if store:
                store.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # --- HTTP -------------------------------------------------------------------------------

    def _send(self, method: str, path: str, **kw) -> tuple[dict, float]:
        """(corps JSON, durée en ms de la tentative réussie). Réessaie 429, 5xx et pannes
        réseau ; le corps d'une erreur n'est pas journalisé (il peut citer le texte envoyé)."""
        for attempt in range(self.max_retries + 1):
            start = time.perf_counter()
            wait = 2.0 ** (attempt + 1)
            try:
                r = self._http.request(method, path, **kw)
            except httpx.TransportError as exc:
                status = type(exc).__name__
            else:
                if r.status_code < 400:
                    return r.json(), (time.perf_counter() - start) * 1000
                status = r.status_code
                if r.status_code not in RETRY_STATUSES:
                    raise ApiError(f"{method} {path} : HTTP {r.status_code} {_error_code(r)}",
                                   r.status_code)
                if (after := r.headers.get("Retry-After", "")).isdigit():
                    wait = float(after)
            if attempt < self.max_retries:
                log.info("%s : %s, nouvel essai dans %.0f s", path, status, wait)
                self._sleep(wait)
        raise ApiError(f"{method} {path} : {status} après {self.max_retries + 1} essais")

    @property
    def product_id(self):
        if not self._product_id:
            data = self._send("GET", "/1/ai")[0]["data"]
            if len(data) != 1:
                raise ApiError(f"{len(data)} produits AI : préciser INFOMANIAK_PRODUCT_ID")
            self._product_id = data[0]["product_id"]
        return self._product_id

    def models(self) -> list[dict]:
        return self._send("GET", "/1/ai/models")[0]["data"]

    def _budget(self, model: Model, chars: int) -> None:
        self.ledger.check(chars / CHARS_PER_TOKEN * model.price / 1e6)

    # --- embeddings -------------------------------------------------------------------------

    def _embed_batch(self, model: Model, texts: list[str]) -> tuple[np.ndarray, Call]:
        """Un lot. Un texte trop long pour un modèle à `max_chars` (413) : on scinde le lot
        pour l'isoler, puis on le raccourcit d'un quart."""
        texts = [t[:model.max_chars] for t in texts]
        try:
            return self._embed_once(model, texts)
        except ApiError as exc:
            if exc.status != 413 or not model.max_chars:
                raise
        if len(texts) == 1:
            if len(texts[0]) < 40:
                raise ApiError(f"{model.name} : texte court refusé", 413)
            return self._embed_batch(model, [texts[0][:len(texts[0]) * 3 // 4]])
        half = len(texts) // 2
        (a, ca), (b, cb) = (self._embed_batch(model, t) for t in (texts[:half], texts[half:]))
        return np.vstack([a, b]), Call(ca.tokens + cb.tokens, ca.chf + cb.chf, ca.ms + cb.ms)

    def _embed_once(self, model: Model, texts: list[str]) -> tuple[np.ndarray, Call]:
        self._budget(model, sum(map(len, texts)))
        body, ms = self._send("POST", f"/2/ai/{self.product_id}/openai/v1/embeddings",
                              json={"model": model.name, "input": texts})
        call = self.ledger.record("embed", model, len(texts),
                                  body["usage"].get("total_tokens", 0), ms)
        rows = sorted(body["data"], key=lambda d: d["index"])
        if len(rows) != len(texts):
            raise ApiError(f"{len(texts)} textes envoyés, {len(rows)} vecteurs reçus")
        vectors = np.array([d["embedding"] for d in rows], dtype=np.float32)
        # Norme 1 : le produit scalaire EST alors le cosinus
        return vectors / np.linalg.norm(vectors, axis=1, keepdims=True), call

    def embed_documents(self, model: Model, texts: list[str], batch: int = BATCH,
                        private: bool = False) -> np.ndarray:
        """Un vecteur par texte, dans l'ordre. Clé du cache = (modèle, sha256 du texte) :
        seuls les textes nouveaux ou modifiés partent à l'API, chacun une seule fois."""
        store = self.private if private else self.cache
        by_key = {sha(model.name, t): t for t in texts}
        known = {k: np.frombuffer(hit[0], np.float32)
                 for k in by_key if (hit := store.get(k))}
        # Par longueur : des lots homogènes (un texte long ne retient pas les courts)
        missing = sorted((k for k in by_key if k not in known), key=lambda k: len(by_key[k]))
        for i in range(0, len(missing), batch):
            keys = missing[i:i + batch]
            vectors, call = self._embed_batch(model, [by_key[k] for k in keys])
            share = Call(call.tokens // len(keys), call.chf / len(keys), call.ms / len(keys))
            store.put([(k, v.tobytes(), share) for k, v in zip(keys, vectors)])
            known.update(zip(keys, vectors))
        return np.stack([known[sha(model.name, t)] for t in texts])

    def embed_query(self, model: Model, text: str) -> tuple[np.ndarray, Call]:
        """Le vecteur d'un CV (avec l'instruction du modèle), et ce qu'il a coûté."""
        prompt = model.query.format(text)
        key = sha(model.name, "query", prompt)
        if self.private and (hit := self.private.get(key)):
            return np.frombuffer(hit[0], np.float32), hit[1]
        vectors, call = self._embed_batch(model, [prompt])
        if self.private:
            self.private.put([(key, vectors[0].tobytes(), call)])
        return vectors[0], call

    # --- reranking --------------------------------------------------------------------------

    def rerank(self, model: Model, query: str, documents: list[str],
               max_tokens: int | None = None) -> tuple[np.ndarray, Call]:
        """Le score de chaque document, dans l'ordre reçu, et le coût de l'appel."""
        key = sha(model.name, "rerank", max_tokens, query, *documents)
        if self.private and (hit := self.private.get(key)):
            return np.frombuffer(hit[0], np.float32), hit[1]
        # Majorant : la requête peut être comptée à chaque document
        self._budget(model, sum(map(len, documents)) + len(query) * len(documents))
        payload = {"model": model.name, "query": query, "documents": documents}
        if max_tokens:
            payload["max_tokens_per_doc"] = max_tokens
        body, ms = self._send("POST", f"/2/ai/{self.product_id}/cohere/v2/rerank", json=payload)
        call = self.ledger.record("rerank", model, len(documents),
                                  body["usage"]["total_tokens"], ms)
        scores = np.full(len(documents), -np.inf, dtype=np.float32)
        for row in body["results"]:
            scores[row["index"]] = row["relevance_score"]
        if self.private:
            self.private.put([(key, scores.tobytes(), call)])
        return scores, call


def _error_code(response: httpx.Response) -> str:
    """Le code d'erreur seul, jamais la description : elle peut citer le texte envoyé."""
    try:
        return str(response.json().get("error", {}).get("code", ""))[:80]
    except (ValueError, AttributeError):
        return ""
