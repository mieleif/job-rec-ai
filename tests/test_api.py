from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from job_rec_ai import api, pipeline, storage
from job_rec_ai.models import Job

OFFERS = [("Data Engineer", "Genève", "Python, SQL, dbt et Airflow pour la plateforme data."),
          ("Développeur IA", "Lausanne", "LLM, RAG, agents et Python en production."),
          ("Comptable", "Genève", "Comptabilité fournisseurs, SAP, clôtures.")]


def _write_db(path, offers=OFFERS):
    con = storage.connect(path)
    jobs = [Job(title=t, company="Acme", url=f"https://acme.example/{i}", location=loc,
                description=d, source="workday") for i, (t, loc, d) in enumerate(offers)]
    storage.upsert_jobs(con, [pipeline.enrich(j) for j in jobs], datetime(2026, 11, 1))
    con.close()


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "jobs.duckdb"
    _write_db(path)
    return path


@pytest.fixture
def client(db, monkeypatch):
    monkeypatch.delenv("JOB_REC_TOKEN", raising=False)
    with TestClient(api.create_app(db)) as c:
        yield c


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_recommend_classe_et_decrit_les_offres(client):
    recos = client.post("/recommend", json={"cv_text": "Ingénieur Python, SQL, dbt", "k": 2}).json()
    assert recos[0]["title"] == "Data Engineer"
    assert recos[0]["job_id"] == recos[0]["url"] == "https://acme.example/0"
    assert recos[0]["company"] == "Acme" and recos[0]["canton"] == "GE"
    assert [r["score"] for r in recos] == sorted((r["score"] for r in recos), reverse=True)
    assert client.get("/status").json()["offers"] == 3


def test_offres_sans_mot_commun_ecartees(client):
    """Score nul = aucun mot en commun : on ne remplit pas le top k avec du hasard."""
    recos = client.post("/recommend", json={"cv_text": "Comptabilité SAP", "k": 10}).json()
    assert [r["title"] for r in recos] == ["Comptable"]


def test_filtre_par_canton(client):
    recos = client.post("/recommend", json={"cv_text": "Python", "k": 10,
                                             "cantons": ["vd"]}).json()
    assert [r["title"] for r in recos] == ["Développeur IA"]


@pytest.mark.parametrize("body", [{"cv_text": "   ", "k": 3}, {"cv_text": "Python", "k": 0},
                                  {"cv_text": "Python", "k": 51}, {"k": 3}])
def test_entrees_invalides(client, body):
    assert client.post("/recommend", json=body).status_code == 422


def test_jeton_exige_si_configure(db, monkeypatch):
    monkeypatch.setenv("JOB_REC_TOKEN", "secret")
    with TestClient(api.create_app(db)) as c:
        body = {"cv_text": "Python", "k": 1}
        assert c.post("/recommend", json=body).status_code == 401
        ok = c.post("/recommend", json=body, headers={"Authorization": "Bearer secret"})
        assert ok.status_code == 200
        assert c.get("/health").status_code == 200  # la sonde reste ouverte


def test_base_absente_503(tmp_path, monkeypatch):
    monkeypatch.delenv("JOB_REC_TOKEN", raising=False)
    with TestClient(api.create_app(tmp_path / "absente.duckdb")) as c:
        assert c.post("/recommend", json={"cv_text": "Python"}).status_code == 503


def test_rechargement_quand_la_base_change(db, monkeypatch):
    index = api.Index(db)
    index.refresh(force=True)
    assert len(index.jobs) == 3
    _write_db(db, OFFERS + [("Juriste", "Genève", "Droit des contrats.")])
    monkeypatch.setattr(api, "REFRESH", 0)
    index.refresh()
    assert len(index.jobs) == 4


def test_status_relit_la_base_apres_une_collecte(db, monkeypatch):
    """Retour du VPS : /status montrait 0 offre jusqu'au premier /recommend."""
    monkeypatch.delenv("JOB_REC_TOKEN", raising=False)
    with TestClient(api.create_app(db)) as c:
        assert c.get("/status").json()["offers"] == 3
        _write_db(db, OFFERS + [("Juriste", "Genève", "Droit des contrats.")])
        monkeypatch.setattr(api, "REFRESH", 0)
        assert c.get("/status").json()["offers"] == 4


def test_base_verrouillee_garde_l_index_precedent(db):
    """Pendant la collecte (écriture par un autre accès), l'ancien index reste servi."""
    index = api.Index(db)
    index.refresh(force=True)
    writer = storage.connect(db)  # ouverte en écriture : la lecture seule est refusée
    try:
        index.mtime = None  # forcer une tentative de rechargement
        index.refresh(force=True)
        assert len(index.jobs) == 3 and index.mtime is None
    finally:
        writer.close()
