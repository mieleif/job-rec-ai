"""Checkpoint M6 : re-ranking.

Contrat attendu (src/job_rec_ai/rank.py) :
- freshness(days_old, half_life_days=14) -> float : 0.5 ** (days_old / half_life_days) ;
  ValueError si days_old < 0.
- combine_scores(candidates: list[dict], weights: dict[str, float]) -> list[dict]
    score = Σ weights[f] * candidat.get(f, 0) ; renvoie les candidats enrichis d'une clé
    "score", triés par score décroissant, sans modifier la liste d'entrée.
"""

import pytest


def test_fraicheur_demi_vie(need):
    """Calculer une fraîcheur exponentielle : 1 au jour 0, 0.5 à une demi-vie, 0.25 à deux."""
    freshness = need("job_rec_ai.rank", "freshness")
    assert freshness(0) == pytest.approx(1.0)
    assert freshness(14) == pytest.approx(0.5)
    assert freshness(28) == pytest.approx(0.25)
    assert freshness(10, half_life_days=10) == pytest.approx(0.5)


def test_fraicheur_age_negatif(need):
    """Refuser un âge négatif (une offre publiée dans le futur, c'est un bug de données)."""
    freshness = need("job_rec_ai.rank", "freshness")
    with pytest.raises(ValueError):
        freshness(-1)


def test_combinaison_des_scores(need):
    """Combiner plusieurs signaux pondérés et trier (une feature manquante compte 0)."""
    combine = need("job_rec_ai.rank", "combine_scores")
    cands = [{"id": "a", "sim": 0.9, "fresh": 0.1},
             {"id": "b", "sim": 0.7, "fresh": 1.0},
             {"id": "c", "sim": 0.8}]
    out = combine(cands, {"sim": 1.0, "fresh": 0.5})
    assert [c["id"] for c in out] == ["b", "a", "c"]
    assert [c["score"] for c in out] == pytest.approx([1.2, 0.95, 0.8])


def test_combinaison_sans_effet_de_bord(need):
    """Ne pas modifier la liste de candidats reçue en entrée."""
    combine = need("job_rec_ai.rank", "combine_scores")
    cands = [{"id": "a", "sim": 0.1}, {"id": "b", "sim": 0.9}]
    combine(cands, {"sim": 1.0})
    assert [c["id"] for c in cands] == ["a", "b"]
    assert "score" not in cands[0]
