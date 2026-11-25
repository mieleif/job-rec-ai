"""Recommandation : BM25 (M3), puis hybride BM25 + vecteurs Qwen3 (M4).

HYBRIDE. BM25 et le cosinus Qwen3-Embedding-8B classent chacun TOUTES les offres, RRF fusionne
les deux classements (voir search.py). C'est la méthode « bm25+qwen3-8b » de l'évaluation, et
BM25 seul reste le repli sans vecteurs ou sans API.

BASELINE. Le CV comme requête BM25 sur les offres actives.

BM25 a été pensé pour des requêtes de 2 à 5 mots ; un CV en fait ~350, dont « et » ×15 et
« ia » ×9. Côté requête, BM25 ne sature rien : un mot répété dans le CV compte autant de
fois. On retire les mots-outils, mais on GARDE les répétitions : elles disent ce que le CV
met en avant. Mesuré le 05.11.2026 sur les 38 offres notées par Leif : nDCG@10 0,775 avec
répétitions, 0,662 dédoublonné (0,740 contre 0,617 avec le profil comme requête).
"""

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from job_rec_ai import embeddings, search
from job_rec_ai.bm25 import BM25, K1, B
from job_rec_ai.cv import without_contact
from job_rec_ai.text import STOPWORDS, tokenize

EMBEDDER = embeddings.EMBEDDERS["qwen3-8b"]
RERANKER = embeddings.RERANKERS["qwen3-0.6b"]
TRUNCATION = 512        # tokens par offre envoyés au reranker
MIN_COVERAGE = 0.9      # part des offres qui doivent avoir un vecteur pour servir l'hybride
SEMANTIC_HEAD = 200     # sans mot commun, une offre ne reste que si les vecteurs la placent là
MAX_QUERY_CHARS = 20_000  # ~6 000 tokens : Infomaniak refuse au-delà de 8 192


def document(job: dict) -> list[str]:
    return tokenize(f"{job['title']} {job['description']}")


def passage(job: dict) -> str:
    """Le texte d'une offre pour les modèles. Une offre Coop n'a que son titre, répété dans
    sa description : on ne l'écrit qu'une fois."""
    title, description = job["title"].strip(), (job["description"] or "").strip()
    return f"{title}. {description}" if description and description != title else title


def query_terms(text: str, unique: bool = False) -> list[str]:
    """Les mots de recherche d'un CV : sans coordonnées, mots-outils ni nombres purs (dates,
    NPA, « 200+ » : ils matcheraient des dates et des adresses d'offres, pas des métiers).
    Les mots mêlant lettres et chiffres restent (« n8n », « b2 »)."""
    words = [w for w in tokenize(without_contact(text))
             if w not in STOPWORDS and any(c.isalpha() for c in w)]
    return list(dict.fromkeys(words)) if unique else words


def rank(jobs: list[dict], cv_text: str, unique: bool = False, k1: float = K1,
         b: float = B, index: BM25 | None = None) -> list[dict]:
    """Toutes les offres, de la plus pertinente à la moins pertinente, avec leur score.
    `index` : un BM25 déjà construit sur ces offres (k1 et b sont alors les siens)."""
    index = index or BM25([document(j) for j in jobs], k1=k1, b=b)
    scores = index.scores(query_terms(cv_text, unique))
    order = sorted(range(len(jobs)), key=lambda i: -scores[i])
    return [{**jobs[i], "score": float(scores[i])} for i in order]


@dataclass(frozen=True)
class Vectors:
    """Les vecteurs des offres, dans l'ordre des offres : `rows[i]` = ligne de l'offre i, ou -1."""
    matrix: np.ndarray
    rows: np.ndarray

    @classmethod
    def load(cls, path: Path, jobs: list[dict]) -> "Vectors":
        return cls(*embeddings.read_vectors(path, EMBEDDER, [passage(j) for j in jobs]))

    @property
    def count(self) -> int:
        return int((self.rows >= 0).sum())

    @property
    def usable(self) -> bool:
        return len(self.rows) > 0 and self.count >= MIN_COVERAGE * len(self.rows)

    def ranking(self, query: np.ndarray) -> list[int]:
        """Les positions des offres qui ont un vecteur, de la plus proche à la plus éloignée."""
        known = np.flatnonzero(self.rows >= 0)
        scores = search.cosine_scores(self.matrix, query)[self.rows[known]]
        return known[np.argsort(-scores, kind="stable")].tolist()


def hybrid_rank(jobs: list[dict], cv_text: str, query: np.ndarray, vectors: Vectors,
                index: BM25 | None = None) -> list[dict]:
    """Les offres par score RRF décroissant. Une offre sans vecteur (nouvelle, pas encore
    encodée) n'est classée que par BM25. Sont écartées celles qui n'ont aucun mot du CV ET que
    les vecteurs ne placent pas en tête : un filtre par canton étroit ne doit pas remonter le
    fond du classement."""
    lexical = rank(jobs, cv_text, index=index)
    semantic = [jobs[i]["url"] for i in vectors.ranking(query)]
    fused = search.rrf_scores([[j["url"] for j in lexical], semantic])
    kept = {j["url"] for j in lexical if j["score"] > 0} | set(semantic[:SEMANTIC_HEAD])
    by_url = {j["url"]: j for j in jobs}
    return [{**by_url[url], "score": score}
            for url, score in sorted(fused.items(), key=lambda item: -item[1]) if url in kept]
