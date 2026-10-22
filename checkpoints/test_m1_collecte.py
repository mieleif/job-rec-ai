"""Checkpoint M1 : collecte.

Contrat attendu :
- job_rec_ai.models.Job : modèle pydantic (title, company, url, location, description,
  language=None, posted_at=None). title vide refusé, url invalide refusée.
- job_rec_ai.connectors.REGISTRY : dict {nom_ats: connecteur}, chaque connecteur ayant
  une méthode parse(payload: dict) -> list[Job]. Une fixture tests/fixtures/<nom_ats>.json
  par connecteur.
- job_rec_ai.dedupe.dedupe(jobs) -> list[Job] : retire les doublons (même URL, ou même
  entreprise + titre + lieu après normalisation casefold/espaces), garde le premier vu.
"""

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"


def _job(Job, **kw):
    base = dict(title="Data Engineer", company="Acme", url="https://acme.example/jobs/1",
                location="Genève", description="Construire des pipelines de données.")
    return Job(**{**base, **kw})


def test_job_valide(need):
    """Créer un Job valide, avec language et posted_at optionnels (None par défaut)."""
    Job = need("job_rec_ai.models", "Job")
    job = _job(Job)
    assert job.title == "Data Engineer"
    assert job.language is None and job.posted_at is None


def test_job_refuse_url_invalide(need):
    """Refuser une URL invalide."""
    Job = need("job_rec_ai.models", "Job")
    with pytest.raises(ValueError):
        _job(Job, url="pas-une-url")


def test_job_refuse_titre_vide(need):
    """Refuser un titre vide ou composé uniquement d'espaces."""
    Job = need("job_rec_ai.models", "Job")
    with pytest.raises(ValueError):
        _job(Job, title="   ")


def test_deux_connecteurs(need):
    """Référencer au moins 2 connecteurs ATS dans REGISTRY."""
    registry = need("job_rec_ai.connectors", "REGISTRY")
    assert len(registry) >= 2, f"{len(registry)} connecteur(s) seulement"


def test_connecteurs_parsent_leurs_fixtures(need):
    """Chaque connecteur transforme sa fixture JSON réelle en une liste non vide de Job."""
    registry = need("job_rec_ai.connectors", "REGISTRY")
    Job = need("job_rec_ai.models", "Job")
    assert registry, "REGISTRY est vide"
    for name, connector in registry.items():
        fixture = FIXTURES / f"{name}.json"
        assert fixture.exists(), f"fixture manquante : tests/fixtures/{name}.json"
        jobs = connector.parse(json.loads(fixture.read_text(encoding="utf-8")))
        assert jobs, f"{name} : aucune offre extraite"
        assert all(isinstance(j, Job) for j in jobs), f"{name} : parse doit renvoyer des Job"


def test_dedupe_meme_url(need):
    """Dédoublonner deux offres ayant la même URL (on garde la première)."""
    Job = need("job_rec_ai.models", "Job")
    dedupe = need("job_rec_ai.dedupe", "dedupe")
    a, b = _job(Job, title="Data Engineer"), _job(Job, title="Data Engineer (H/F)")
    assert dedupe([a, b]) == [a]


def test_dedupe_normalise_le_titre(need):
    """Considérer « Data  Engineer » et « data engineer » chez la même entreprise, au même lieu, comme un doublon."""
    Job = need("job_rec_ai.models", "Job")
    dedupe = need("job_rec_ai.dedupe", "dedupe")
    a = _job(Job, title="Data  Engineer ", url="https://acme.example/jobs/1")
    b = _job(Job, title="data engineer", url="https://acme.example/jobs/2")
    assert dedupe([a, b]) == [a]


def test_dedupe_garde_les_lieux_differents(need):
    """Garder deux offres identiques mais situées dans des lieux différents."""
    Job = need("job_rec_ai.models", "Job")
    dedupe = need("job_rec_ai.dedupe", "dedupe")
    a = _job(Job, location="Genève", url="https://acme.example/jobs/1")
    b = _job(Job, location="Lausanne", url="https://acme.example/jobs/2")
    assert dedupe([a, b]) == [a, b]
