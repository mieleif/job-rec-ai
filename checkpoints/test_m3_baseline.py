"""Checkpoint M3 : baseline et évaluation.

Contrat attendu (src/job_rec_ai/koans.py, écrit À LA MAIN, sans scikit-learn) :
- cosine_similarity(a, b) -> float ; ValueError si un vecteur est nul.
- tfidf(docs: list[list[str]]) -> list[dict[str, float]]
    tf = occurrences / nombre de mots du document ; idf = ln(N / df).
- precision_at_k(ranked: list[str], relevant: set[str], k: int) -> float
- mean_reciprocal_rank(runs: list[tuple[list[str], set[str]]]) -> float
- ndcg_at_k(ranked: list[str], relevance: dict[str, float], k: int) -> float
    DCG = Σ rel_i / log2(i + 1), i = 1..k ; normalisé par le DCG idéal ; 0 si rien de pertinent.
"""

import math

import pytest


def test_cosinus_cas_simples(need):
    """Calculer la similarité cosinus : orthogonaux = 0, colinéaires = 1, opposés = -1."""
    cos = need("job_rec_ai.koans", "cosine_similarity")
    assert cos([1, 0], [0, 1]) == pytest.approx(0)
    assert cos([1, 2], [2, 4]) == pytest.approx(1)
    assert cos([1, 0], [-1, 0]) == pytest.approx(-1)
    assert cos([1, 1], [1, 0]) == pytest.approx(1 / math.sqrt(2))


def test_cosinus_vecteur_nul(need):
    """Lever une ValueError sur un vecteur nul (la division par zéro n'a pas de sens)."""
    cos = need("job_rec_ai.koans", "cosine_similarity")
    with pytest.raises(ValueError):
        cos([0, 0], [1, 2])


def test_tfidf_from_scratch(need):
    """Calculer TF-IDF : un mot présent partout pèse 0, un mot rare pèse tf·ln(N/df)."""
    tfidf = need("job_rec_ai.koans", "tfidf")
    out = tfidf([["python", "sql"], ["python", "excel", "excel", "vba"]])
    assert out[0]["python"] == pytest.approx(0)
    assert out[0]["sql"] == pytest.approx(0.5 * math.log(2))
    assert out[1]["excel"] == pytest.approx(0.5 * math.log(2))
    assert out[1]["vba"] == pytest.approx(0.25 * math.log(2))


def test_precision_at_k(need):
    """Calculer precision@k = pertinents dans le top k / k."""
    p_at_k = need("job_rec_ai.koans", "precision_at_k")
    ranked, relevant = ["a", "b", "c", "d"], {"a", "c"}
    assert p_at_k(ranked, relevant, 1) == pytest.approx(1.0)
    assert p_at_k(ranked, relevant, 2) == pytest.approx(0.5)
    assert p_at_k(ranked, relevant, 4) == pytest.approx(0.5)


def test_mrr(need):
    """Calculer le MRR : moyenne de 1 / rang du premier résultat pertinent (0 si aucun)."""
    mrr = need("job_rec_ai.koans", "mean_reciprocal_rank")
    assert mrr([(["a", "b"], {"a"}), (["x", "y", "b"], {"b"})]) == pytest.approx((1 + 1 / 3) / 2)
    assert mrr([(["x", "y"], {"a"})]) == pytest.approx(0)


def test_ndcg(need):
    """Calculer nDCG@k avec des pertinences graduées (1.0 pour un classement parfait)."""
    ndcg = need("job_rec_ai.koans", "ndcg_at_k")
    rel = {"a": 3, "b": 2, "c": 3}
    assert ndcg(["a", "c", "b"], rel, 3) == pytest.approx(1.0)
    dcg = 3 + 2 / math.log2(3) + 3 / 2
    idcg = 3 + 3 / math.log2(3) + 2 / 2
    assert ndcg(["a", "b", "c"], rel, 3) == pytest.approx(dcg / idcg)
    assert ndcg(["x", "y"], rel, 2) == pytest.approx(0)
