"""Recherche : cosinus exhaustif, fusion de classements (RRF), chunks.

Recherche exhaustive (« brute force ») en numpy : 5 000 vecteurs × 4 096 dimensions = 20
millions de multiplications, quelques ms, résultat exact. Un index HNSW (graphe de voisins)
échangerait un peu de rappel contre de la vitesse : utile vers le million de vecteurs.
"""

from collections import defaultdict

import numpy as np

RRF_K = 60  # valeur de l'article d'origine (Cormack et al., 2009), devenue le standard


def rrf_scores(rankings: list[list[str]], k: int = RRF_K) -> dict[str, float]:
    """Reciprocal Rank Fusion : score(d) = Σ 1 / (k + rang), rang commençant à 1.

    Les scores BM25 (0 à 300) et les cosinus (0,3 à 0,7) n'ont pas la même unité : on ne
    garde que les rangs. k amortit la tête : avec k = 60, être 1ᵉʳ d'une seule liste vaut
    moins qu'être 10ᵉ des deux ; avec k = 1, un 1ᵉʳ rang écrase tout."""
    scores: dict[str, float] = defaultdict(float)
    for ranking in rankings:
        for rank, item in enumerate(ranking, 1):
            scores[item] += 1 / (k + rank)
    return scores


def rrf_fuse(rankings: list[list[str]], k: int = RRF_K) -> list[str]:
    """Les éléments par score RRF décroissant (tri stable : à égalité, l'ordre d'arrivée)."""
    scores = rrf_scores(rankings, k)
    return sorted(scores, key=lambda item: -scores[item])


def cosine_scores(matrix: np.ndarray, query: np.ndarray) -> np.ndarray:
    """Cosinus de la requête avec chaque ligne (vecteurs de norme 1 : produit scalaire)."""
    return matrix @ query


def cosine_search(ids: list[str], matrix: np.ndarray, query: np.ndarray) -> list[str]:
    """Tous les documents, du plus proche au plus éloigné de la requête."""
    return [ids[i] for i in np.argsort(-cosine_scores(matrix, query), kind="stable")]


def max_by_document(scores: np.ndarray, owners: np.ndarray, n: int) -> np.ndarray:
    """Le score d'un document = celui de son meilleur chunk (owners[c] = son document)."""
    best = np.full(n, -np.inf, dtype=scores.dtype)
    np.maximum.at(best, owners, scores)
    return best


def hybrid(rankings: list[list[str]], depth: int | None = None, k: int = RRF_K) -> list[str]:
    """Recherche hybride : les classements (BM25, vecteurs) calculés EN PARALLÈLE, sur tout
    le corpus, puis fusionnés. Jamais l'un en filtre de l'autre : un filtre BM25 perdrait
    les offres sans mot commun avec le CV, celles que les vecteurs sont là pour trouver.
    `depth` : ne fusionner que la tête de chaque classement (None : tout)."""
    return rrf_fuse([r[:depth] for r in rankings], k)
