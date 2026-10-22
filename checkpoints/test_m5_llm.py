"""Checkpoint M5 : enrichissement LLM.

Contrat attendu :
- job_rec_ai.models.JobFacts (pydantic) :
    skills: list[str]
    seniority: "junior" | "mid" | "senior" | "lead" | "unknown"
    remote: "onsite" | "hybrid" | "remote" | "unknown"
    languages: list[str]  (codes ISO à 2 lettres, normalisés en minuscules)
    salary_min / salary_max: int | None (min ≤ max si les deux sont présents)
- job_rec_ai.llm.estimate_cost(input_tokens, output_tokens, price_in_per_mtok, price_out_per_mtok) -> float
"""

import pytest


def _facts(JobFacts, **kw):
    base = dict(skills=["Python", "SQL"], seniority="mid", remote="hybrid", languages=["fr", "en"])
    return JobFacts(**{**base, **kw})


def test_jobfacts_valide(need):
    """Créer des JobFacts valides, salaire absent par défaut."""
    JobFacts = need("job_rec_ai.models", "JobFacts")
    f = _facts(JobFacts)
    assert f.skills == ["Python", "SQL"]
    assert f.salary_min is None and f.salary_max is None


def test_jobfacts_refuse_categorie_inventee(need):
    """Refuser une séniorité ou un mode de télétravail inventés par le LLM."""
    JobFacts = need("job_rec_ai.models", "JobFacts")
    with pytest.raises(ValueError):
        _facts(JobFacts, seniority="ninja")
    with pytest.raises(ValueError):
        _facts(JobFacts, remote="parfois")


def test_jobfacts_normalise_les_langues(need):
    """Normaliser les codes de langue (« FR » → « fr ») et refuser les codes invalides."""
    JobFacts = need("job_rec_ai.models", "JobFacts")
    assert _facts(JobFacts, languages=["FR", " En "]).languages == ["fr", "en"]
    with pytest.raises(ValueError):
        _facts(JobFacts, languages=["français"])


def test_jobfacts_salaire_coherent(need):
    """Refuser un salaire minimum supérieur au salaire maximum."""
    JobFacts = need("job_rec_ai.models", "JobFacts")
    assert _facts(JobFacts, salary_min=90_000, salary_max=120_000).salary_max == 120_000
    with pytest.raises(ValueError):
        _facts(JobFacts, salary_min=150_000, salary_max=100_000)


def test_estimation_du_cout(need):
    """Estimer le coût d'un appel LLM à partir des tokens et des prix par million de tokens."""
    estimate_cost = need("job_rec_ai.llm", "estimate_cost")
    assert estimate_cost(1_000_000, 500_000, 1.0, 5.0) == pytest.approx(3.5)
    assert estimate_cost(0, 0, 1.0, 5.0) == pytest.approx(0)
