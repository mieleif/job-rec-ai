"""Checkpoint M8 : production.

Contrat attendu (src/job_rec_ai/api.py) : une application FastAPI nommée `app`.
- GET /health → 200 {"status": "ok"}
- POST /recommend {"cv_text": str, "k": int (1..50, défaut 10)}
    → 200, liste d'au plus k objets {"job_id", "title", "score"}, triés par score décroissant
    → 422 si cv_text est vide ou si k est hors limites
"""

import pytest

CV = "Ingénieur mécanique EPFL, Python, SQL, analyse de données, français et anglais."


@pytest.fixture
def client(need):
    app = need("job_rec_ai.api", "app")
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        pytest.fail("fastapi[standard] n'est pas installé (uv add 'fastapi[standard]')", pytrace=False)
    return TestClient(app)


def test_health(client):
    """Répondre {"status": "ok"} sur GET /health."""
    r = client.get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_recommend(client):
    """Renvoyer au plus k recommandations (job_id, title, score) triées par score."""
    r = client.post("/recommend", json={"cv_text": CV, "k": 3})
    assert r.status_code == 200
    recos = r.json()
    assert 0 < len(recos) <= 3
    assert all({"job_id", "title", "score"} <= set(x) for x in recos)
    scores = [x["score"] for x in recos]
    assert scores == sorted(scores, reverse=True)


def test_recommend_valide_les_entrees(client):
    """Refuser (422) un CV vide ou un k hors limites."""
    assert client.post("/recommend", json={"cv_text": "", "k": 3}).status_code == 422
    assert client.post("/recommend", json={"cv_text": CV, "k": 500}).status_code == 422
    assert client.post("/recommend", json={"cv_text": CV, "k": 0}).status_code == 422
