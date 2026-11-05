"""Les briques de M3, écrites à la main pour les comprendre (sans scikit-learn).

Contrat : checkpoints/test_m3_baseline.py.
"""

import math
from collections import Counter

import numpy as np


def cosine_similarity(a, b) -> float:
    """cos θ = a·b / (‖a‖ ‖b‖) : l'angle entre deux vecteurs, indépendamment de leur longueur.

    Pour des comptes de mots (tous ≥ 0), le résultat est dans [0, 1] : 1 = même direction
    (même profil de vocabulaire, quelle que soit la longueur du texte), 0 = aucun mot commun.
    """
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    norms = np.linalg.norm(a) * np.linalg.norm(b)
    if norms == 0:  # un vecteur nul n'a pas de direction : l'angle n'est pas défini
        raise ValueError("similarité cosinus indéfinie pour un vecteur nul")
    return float(a @ b / norms)


def tfidf(docs: list[list[str]]) -> list[dict[str, float]]:
    """Poids TF-IDF de chaque mot de chaque document (documents déjà découpés en mots).

    tf = occurrences / nombre de mots du document : la part du document qu'occupe le mot.
    idf = ln(N / df), df = nombre de documents qui contiennent le mot : un mot présent
    partout (« et ») vaut ln(1) = 0, un mot rare vaut beaucoup. Le produit dit « ce mot est
    fréquent ICI mais rare AILLEURS » : c'est ce qui caractérise un document.
    """
    n = len(docs)
    df = Counter(word for doc in docs for word in set(doc))
    idf = {word: math.log(n / count) for word, count in df.items()}
    return [{word: count / len(doc) * idf[word] for word, count in Counter(doc).items()}
            for doc in docs]


# --- métriques de classement ----------------------------------------------------------------
# Elles ne regardent que le haut de la liste : un utilisateur lit 10 offres, pas 1 700.


def precision_at_k(ranked: list[str], relevant: set[str], k: int) -> float:
    """Part des k premiers résultats qui sont pertinents. Simple, mais aveugle à l'ordre
    dans le top k (pertinent en 1ᵉʳ ou en 10ᵉ : même score)."""
    return sum(item in relevant for item in ranked[:k]) / k


def mean_reciprocal_rank(runs: list[tuple[list[str], set[str]]]) -> float:
    """Moyenne de 1 / rang du PREMIER pertinent (0 si aucun) : « combien faut-il lire avant
    de trouver quelque chose ? ». 1ᵉʳ → 1, 2ᵉ → 0,5, 10ᵉ → 0,1."""
    def reciprocal(ranked, relevant):
        return next((1 / rank for rank, item in enumerate(ranked, 1) if item in relevant), 0.0)

    return sum(reciprocal(r, rel) for r, rel in runs) / len(runs)


def ndcg_at_k(ranked: list[str], relevance: dict[str, float], k: int) -> float:
    """DCG = Σ rel_i / log2(i + 1) sur le top k : pertinence graduée, escomptée par le rang
    (le 1ᵉʳ compte plein, le 3ᵉ moitié). Divisé par le DCG du classement idéal → [0, 1]."""
    def dcg(gains):
        return sum(g / math.log2(i + 1) for i, g in enumerate(gains, 1))

    ideal = dcg(sorted(relevance.values(), reverse=True)[:k])
    if ideal == 0:
        return 0.0
    return dcg([relevance.get(item, 0) for item in ranked[:k]]) / ideal
