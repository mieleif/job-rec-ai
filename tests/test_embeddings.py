import json

import httpx
import numpy as np
import pytest

from job_rec_ai import embeddings, evaluation, koans, search
from job_rec_ai.cv import for_api
from job_rec_ai.rerank import rerank
from job_rec_ai.text import chunk_text

QWEN = embeddings.EMBEDDERS["qwen3-8b"]
BGE = embeddings.RERANKERS["bge-v2-m3"]
SECRET = "Expérience confidentielle chez Zorglub"


def _vector(text):
    """Embedding jouet : des comptes de lettres."""
    return [text.lower().count(c) + 0.1 for c in "aeinp"]


@pytest.fixture
def api(tmp_path):
    """Fausse API : `calls` garde les corps reçus, `fail` les statuts à renvoyer d'abord."""
    class Api:
        calls: list = []
        fail: list = []
        sleeps: list = []

        def handler(self, request):
            if self.fail:
                return httpx.Response(self.fail.pop(0), headers={"Retry-After": "7"}, json={
                    "error": {"code": "bad", "description": request.content.decode()}})
            if request.url.path == "/1/ai":
                return httpx.Response(200, json={"data": [{"product_id": 42}]})
            body = json.loads(request.content)
            if "mini" in body["model"] and any(len(t) > 100 for t in body["input"]):
                return httpx.Response(413)
            self.calls.append((request.url.path, body))
            if "rerank" in request.url.path:
                results = [{"index": i, "relevance_score": len(d)}
                           for i, d in enumerate(body["documents"])]
                return httpx.Response(200, json={"results": results[::-1],
                                                 "usage": {"total_tokens": 1000}})
            data = [{"index": i, "embedding": _vector(t)} for i, t in enumerate(body["input"])]
            return httpx.Response(200, json={"data": data[::-1],  # dans le désordre
                                             "usage": {"total_tokens": 1_000_000}})

        def client(self, budget=3.0):
            return embeddings.Client(
                "cle-de-test", ledger=embeddings.Ledger(tmp_path / "usage.jsonl", budget),
                cache=tmp_path / "jobs.sqlite", private_cache=tmp_path / "private.sqlite",
                transport=httpx.MockTransport(self.handler), sleep=self.sleeps.append)

    a = Api()
    a.calls, a.fail, a.sleeps = [], [], []
    return a


def test_seuls_les_textes_nouveaux_partent_a_l_api(api):
    with api.client() as client:
        first = client.embed_documents(QWEN, ["pain", "vin", "pain"])
        assert np.allclose(first[0], first[2])  # ordre gardé, doublon encodé une fois
    with api.client() as client:  # nouveau processus : le cache est sur disque
        second = client.embed_documents(QWEN, ["vin", "eau", "pain"])
    assert [sorted(b["input"]) for _, b in api.calls] == [["pain", "vin"], ["eau"]]
    assert np.allclose(second[0], first[1]) and np.allclose(second[2], first[0])
    assert np.allclose(np.linalg.norm(second, axis=1), 1)


def test_le_cache_distingue_les_modeles(api):
    with api.client() as client:
        for model in (QWEN, embeddings.EMBEDDERS["gemma2"]):
            client.embed_documents(model, ["pain"])
    assert [b["model"] for _, b in api.calls] == [QWEN.name, "bge_multilingual_gemma2"]


def test_envoi_par_lots(api):
    with api.client() as client:
        client.embed_documents(QWEN, [f"texte {i}" for i in range(5)], batch=2)
    assert [len(b["input"]) for _, b in api.calls] == [2, 2, 1]


def test_nouvelles_tentatives_puis_erreur_sans_citer_le_texte(api):
    api.fail = [429, 503]
    with api.client() as client:
        client._product_id = 42
        client.embed_documents(QWEN, ["pain"])
        assert api.sleeps == [7, 7]
        api.fail = [422]  # pas une panne passagère : pas de nouvel essai
        with pytest.raises(embeddings.ApiError) as error:
            client.embed_query(QWEN, SECRET)
    assert "Zorglub" not in str(error.value) and "422 bad" in str(error.value)


def test_un_texte_trop_long_est_raccourci_sans_toucher_aux_autres(api):
    with api.client() as client:
        out = client.embed_documents(embeddings.EMBEDDERS["minilm"], ["pain", "vin", "n" * 900])
    assert out.shape == (3, 5)
    sent = [t for _, b in api.calls for t in b["input"]]
    assert {"pain", "vin"} <= set(sent) and max(map(len, sent)) <= 100


def test_tokens_et_chf_journalises_sans_texte(api, tmp_path):
    with api.client() as client:
        _, call = client.embed_query(QWEN, SECRET)
        _, again = client.embed_query(QWEN, SECRET)
    assert call.tokens == 1_000_000 and call.chf == pytest.approx(0.07)
    assert again == call and len(api.calls) == 1  # relu : même coût affiché, rien de dépensé
    (line,) = (tmp_path / "usage.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(line)["chf"] == pytest.approx(0.07)
    for path in tmp_path.iterdir():
        assert "Zorglub".encode() not in path.read_bytes()


def test_plafond_verifie_avant_l_appel_et_entre_deux_lancements(api):
    with api.client(budget=0.1) as client:
        client.embed_documents(QWEN, ["pain"])
    with api.client(budget=0.1) as client:
        assert client.ledger.spent == pytest.approx(0.07)
        with pytest.raises(embeddings.BudgetExceeded):
            client.embed_documents(QWEN, ["x" * 2_000_000])
    assert len(api.calls) == 1


def test_le_cv_ne_va_que_dans_le_cache_prive(api, tmp_path):
    with api.client() as client:
        client.embed_query(QWEN, "cv")
        client.rerank(BGE, "cv", ["a"])
        count = "SELECT count(*) FROM cache"
        assert client.cache.db.execute(count).fetchone() == (0,)
        assert client.private.db.execute(count).fetchone() == (2,)


def test_rerank_reclasse_et_transmet_la_troncature(api):
    texts = {"u1": "court", "u2": "beaucoup plus long", "u3": "moyennement"}
    with api.client() as client:
        ranked, call = rerank(client, BGE, "cv", ["u1", "u2", "u3"], texts, max_tokens=512)
        rerank(client, BGE, "cv", ["u1", "u2", "u3"], texts)
    assert ranked == ["u2", "u3", "u1"] and call.chf == pytest.approx(1e-5)
    assert [b.get("max_tokens_per_doc") for _, b in api.calls] == [512, None]


def test_sans_cle_pas_de_client(monkeypatch):
    monkeypatch.delenv("INFOMANIAK_API_TOKEN", raising=False)
    assert embeddings.Client.from_env() is None


def test_le_texte_envoye_n_a_ni_coordonnees_ni_nom():
    cv = "Léa Martin\n1203 Genève | lea@ex.ch\nIngénieure data\nProjet léa.dev"
    assert for_api(cv, ["léa"]) == "Ingénieure data"


def test_chunks_couvrent_tout_le_texte():
    words = [f"w{i}" for i in range(47)]
    chunks = chunk_text(" ".join(words), 10, 3)
    assert [w for c in chunks for w in c.split() if w == "w46"] == ["w46"]
    assert {w for c in chunks for w in c.split()} == set(words)


def test_recall_et_meilleur_chunk():
    assert koans.recall_at_k(["a", "b", "c"], {"a", "c"}, 2) == 0.5
    assert koans.recall_at_k(["a"], set(), 2) == 0.0
    best = search.max_by_document(np.array([0.1, 0.9, 0.5]), np.array([0, 0, 1]), 2)
    assert best.tolist() == [0.9, 0.5]


def test_evaluation_des_methodes_api(api, tmp_path):
    jobs = [{"url": f"u{i}", "title": t, "company": "Acme", "description": d}
            for i, (t, d) in enumerate([("Boulanger", "pain"), ("IA", "IA"), ("Data", "SQL")])]
    cv = tmp_path / "cv.md"
    cv.write_text("Moi Dupont\nIngénieur IA", encoding="utf-8")
    es = evaluation.EvalSet(tmp_path / "moi.json", "moi", {"cv": str(cv)}, {"u1": 2, "u0": 0})
    with api.client() as client:
        methods = evaluation.api_methods(client, "moi")
        rows = evaluation.evaluate(es, evaluation.Corpus.of(jobs), k=2, methods=methods)
    assert {r.run for r in rows} == {f"{m} · cv" for m in methods}
    full = next(r for r in rows if r.run == "bm25+qwen3-8b > bge-v2-m3@512 · cv")
    assert set(full.trace.steps) == {"bm25", "embedding", "cosinus", "rrf", "rerank"}
    assert full.trace.chf == pytest.approx(0.07 + 1e-5) and full.recall == 1.0
    sent = json.dumps([b for _, b in api.calls])
    assert "Dupont" not in sent
    assert evaluation.passage(jobs[1]) == "IA"  # titre répété en description : une seule fois
