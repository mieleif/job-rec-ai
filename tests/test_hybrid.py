"""/recommend hybride : classement, replis, et rien du CV sur disque ni dans les logs."""

import json
import logging
from datetime import datetime

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient

from job_rec_ai import api, cli, embeddings, evaluation, pipeline, recommend, storage
from job_rec_ai.models import Job

# Vecteurs jouets de 4096 dimensions : un axe par sujet. « Prévisions » n'a aucun mot du CV.
TOPICS = {"données": 0, "prévisions": 0, "comptab": 1}
OFFERS = [("Prévisions", "Genève", "Statistiques et apprentissage."),
          ("Comptable", "Genève", "Comptabilité fournisseurs, SAP, rigueur."),
          ("Analyste", "Lausanne", "Données, SQL, rigueur.")]
CV = "Ingénieure données, SQL, rigueur\nzorglub@example.ch"


def _vector(text):
    v = np.full(4096, 1e-3)
    for word, axis in TOPICS.items():
        if word in text.lower():
            v[axis] += 1
    return v.tolist()


class FakeApi:
    def __init__(self):
        self.calls, self.down = [], False

    def __call__(self, request):
        if self.down:
            raise httpx.ReadTimeout("trop lent")
        body = json.loads(request.content)
        self.calls.append(body)
        if "rerank" in request.url.path:  # préfère les textes courts
            return httpx.Response(200, json={"usage": {"total_tokens": 10}, "results": [
                {"index": i, "relevance_score": 1 / len(d)}
                for i, d in enumerate(body["documents"])]})
        return httpx.Response(200, json={"usage": {"total_tokens": 10}, "data": [
            {"index": i, "embedding": _vector(t)} for i, t in enumerate(body["input"])]})


def _write_db(path, offers):
    con = storage.connect(path)
    jobs = [Job(title=t, company="Acme", url=f"https://acme.example/{i}", location=loc,
                description=d, source="workday") for i, (t, loc, d) in enumerate(offers)]
    storage.upsert_jobs(con, [pipeline.enrich(j) for j in jobs], datetime(2026, 11, 1))
    con.close()


@pytest.fixture
def fake(monkeypatch):
    fake = FakeApi()
    init = embeddings.Client.__init__

    def patched(self, *args, **kw):
        init(self, *args, **kw | {"transport": httpx.MockTransport(fake)})

    monkeypatch.setattr(embeddings.Client, "__init__", patched)
    monkeypatch.setenv("INFOMANIAK_API_TOKEN", "cle-de-test")
    monkeypatch.setenv("INFOMANIAK_PRODUCT_ID", "42")
    for name in ("JOB_REC_TOKEN", "JOB_REC_RERANK", "JOB_REC_BUDGET_CHF"):
        monkeypatch.delenv(name, raising=False)
    return fake


@pytest.fixture
def db(tmp_path):
    _write_db(tmp_path / "jobs.duckdb", OFFERS)
    return tmp_path / "jobs.duckdb"


def _titles(client, cv=CV, **body):
    r = client.post("/recommend", json={"cv_text": cv, **body})
    assert r.status_code == 200
    scores = [j["score"] for j in r.json()]
    assert scores == sorted(scores, reverse=True)
    return [j["title"] for j in r.json()]


def _embed(db, *options):
    cli.main(["--db", str(db), "embed", *options])


def test_l_hybride_trouve_une_offre_sans_mot_commun(fake, db):
    _embed(db)
    with TestClient(api.create_app(db)) as c:
        assert c.get("/status").json() | {"loaded_at": 0} == {
            "offers": 3, "loaded_at": 0, "ranking": "hybrid", "vectors": 3, "fallbacks": 0}
        assert _titles(c) == ["Analyste", "Prévisions", "Comptable"]
        assert _titles(c, cantons=["GE"], k=1) == ["Prévisions"]


def test_sans_jeton_ou_sans_vecteurs_c_est_bm25(fake, db, monkeypatch):
    with TestClient(api.create_app(db)) as c:  # `embed` n'a pas encore tourné
        assert c.get("/status").json()["ranking"] == "bm25"
        bm25 = _titles(c)
    assert "Prévisions" not in bm25 and not fake.calls
    _embed(db)
    monkeypatch.delenv("INFOMANIAK_API_TOKEN")
    with TestClient(api.create_app(db)) as c:
        assert c.get("/status").json()["ranking"] == "bm25"
        assert _titles(c) == bm25


def test_panne_ou_plafond_atteint_repli_sur_bm25_sans_citer_le_cv(fake, db, monkeypatch, caplog):
    _embed(db)
    caplog.set_level(logging.DEBUG)
    with TestClient(api.create_app(db)) as c:
        fake.down = True
        assert "Prévisions" not in _titles(c)
        assert c.get("/status").json()["fallbacks"] == 1
    fake.down = False
    monkeypatch.setenv("JOB_REC_BUDGET_CHF", "0.0000001")
    with TestClient(api.create_app(db)) as c:
        before = len(fake.calls)
        assert "Prévisions" not in _titles(c) and len(fake.calls) == before
    assert "BM25 seul" in caplog.text
    assert "données" not in caplog.text and "zorglub" not in caplog.text


def test_le_cv_part_sans_coordonnees_et_ne_reste_pas_sur_disque(fake, db):
    _embed(db)
    cache = embeddings.Store(db.parent / "embeddings/infomaniak.sqlite")
    offers = cache.db.execute("SELECT count(*) FROM cache").fetchone()
    with TestClient(api.create_app(db)) as c:
        _titles(c)
        _titles(c, cv="données " * 5_000)
    sent = [t for call in fake.calls for t in call["input"]]
    assert not any("zorglub" in t for t in sent)
    assert max(map(len, sent)) <= recommend.MAX_QUERY_CHARS + len(recommend.EMBEDDER.query)
    assert cache.db.execute("SELECT count(*) FROM cache").fetchone() == offers
    cache.close()
    assert sorted(p.name for p in db.parent.rglob("*") if p.is_file()) == [
        "infomaniak.sqlite", "jobs.duckdb", "usage.jsonl"]
    assert "données" not in (db.parent / "embeddings/usage.jsonl").read_text(encoding="utf-8")


def test_vecteurs_ecrits_apres_le_chargement_pris_en_compte(fake, db, monkeypatch):
    monkeypatch.setattr(api, "REFRESH", 0)
    with TestClient(api.create_app(db)) as c:
        assert c.get("/status").json()["ranking"] == "bm25"
        _embed(db)
        assert c.get("/status").json()["ranking"] == "hybrid"


def test_cache_de_vecteurs_abime_c_est_bm25(fake, db):
    (db.parent / "embeddings").mkdir()
    (db.parent / "embeddings/infomaniak.sqlite").write_bytes(b"pas une base SQLite" * 100)
    with TestClient(api.create_app(db)) as c:
        assert c.get("/status").json()["ranking"] == "bm25"
        assert _titles(c)


def test_couverture_partielle(fake, db):
    """Une offre sans vecteur reste classée par BM25 ; trop d'offres sans vecteur : BM25 seul."""
    rows = np.array([0, 0, -1])
    matrix = np.array([_vector("données")], dtype=np.float32)
    vectors = recommend.Vectors(matrix, rows)
    assert vectors.count == 2 and not vectors.usable
    assert recommend.Vectors(matrix, np.array([0] * 9 + [-1])).usable
    assert vectors.ranking(matrix[0]) == [0, 1]
    jobs = [{"url": str(i), "title": t, "description": d} for i, (t, _, d) in enumerate(OFFERS)]
    ranked = recommend.hybrid_rank(jobs, CV, matrix[0], vectors)
    assert {j["title"] for j in ranked} == {"Prévisions", "Comptable", "Analyste"}


def test_sans_mot_commun_ni_tete_semantique_ecartee(monkeypatch):
    monkeypatch.setattr(recommend, "SEMANTIC_HEAD", 1)
    jobs = [{"url": str(i), "title": t, "description": ""} for i, t in
            enumerate(["données", "prévisions", "boulanger"])]
    matrix = np.array([_vector(j["title"]) for j in jobs], dtype=np.float32)
    ranked = recommend.hybrid_rank(jobs, "données", matrix[0],
                                   recommend.Vectors(matrix, np.arange(3)))
    assert [j["title"] for j in ranked] == ["données"]


def test_meme_classement_que_la_methode_evaluee(fake, tmp_path):
    """Ce qui est servi est ce qui est mesuré : « bm25+qwen3-8b » de l'évaluation."""
    jobs = [{"url": f"u{i}", "title": t, "description": d} for i, (t, _, d) in enumerate(OFFERS)]
    with embeddings.Client.from_env(ledger=embeddings.Ledger(tmp_path / "u.jsonl"),
                                    cache=tmp_path / "c.sqlite",
                                    private_cache=tmp_path / "p.sqlite") as client:
        corpus = evaluation.Corpus.of(jobs)
        method = evaluation.api_methods(client, "x", ("qwen3-8b",))["bm25+qwen3-8b"]
        expected = method(corpus, CV, evaluation.Trace())
        query, _ = client.embed_query(recommend.EMBEDDER, api.api_text(CV))
        vectors = recommend.Vectors.load(tmp_path / "c.sqlite", jobs)
    assert [j["url"] for j in recommend.hybrid_rank(jobs, CV, query, vectors)] == expected


def test_reranker_eteint_par_defaut_et_apres_les_filtres(fake, db, monkeypatch):
    _embed(db)
    monkeypatch.setenv("JOB_REC_RERANK", "1")
    with TestClient(api.create_app(db)) as c:
        assert _titles(c)[0] == "Analyste"  # texte le plus court
        _titles(c, cantons=["VD"])
    assert [len(call["documents"]) for call in fake.calls if "documents" in call] == [3, 1]
    assert all(call["max_tokens_per_doc"] == 512 for call in fake.calls if "documents" in call)


def test_embed_ne_paie_que_le_nouveau_et_nettoie(fake, db):
    _embed(db)
    _write_db(db, [("Boulanger", "Genève", "Pain."), *OFFERS[1:]])
    _embed(db, "--prune")
    assert [len(call["input"]) for call in fake.calls] == [3, 1]
    store = embeddings.Store(db.parent / "embeddings/infomaniak.sqlite")
    assert store.db.execute("SELECT count(*) FROM cache").fetchone() == (3,)
    store.close()


def test_plafond_mensuel(tmp_path):
    path = tmp_path / "usage.jsonl"
    path.write_text('{"at": "2020-01-31T10:00:00", "chf": 5.0}\n', encoding="utf-8")
    monthly = embeddings.Ledger(path, 1.0, monthly=True)
    assert monthly.spent == 0
    monthly.spent, monthly._month = 0.99, "2020-01"  # processus lancé le mois précédent
    monthly.check(0.5)
    with pytest.raises(embeddings.BudgetExceeded):
        embeddings.Ledger(path, 1.0).check(0.1)
