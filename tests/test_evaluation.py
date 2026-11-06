import json

import numpy as np
import pytest

from job_rec_ai import annotation, embeddings, evaluation

JOBS = [{"url": f"https://ex.ch/{i}", "title": t, "company": "Acme", "description": d}
        for i, (t, d) in enumerate([
            ("Data Engineer", "Python, SQL, dbt, Airflow."),
            ("Développeur IA", "LLM, RAG, Python, agents."),
            ("Comptable", "Comptabilité fournisseurs, SAP."),
            ("Infirmier", "Soins intensifs, nuit."),
            ("Boulanger", "Pain, viennoiseries."),
            ("Juriste", "Droit des contrats."),
        ])]


@pytest.fixture(autouse=True)
def fake_embeddings(monkeypatch, tmp_path):
    """Pas de vrai modèle dans les tests (lent, téléchargement) ni d'écriture dans le vrai
    cache : un « embedding » jouet, le nombre de lettres « i » et « a » du texte."""
    def encode(texts, kind):
        v = np.array([[t.lower().count("i"), t.lower().count("a"), 1.0] for t in texts])
        return v / np.linalg.norm(v, axis=1, keepdims=True)

    monkeypatch.setattr(embeddings, "encode", encode)
    monkeypatch.setattr(embeddings, "CACHE_DIR", tmp_path / "embeddings")


@pytest.fixture
def corpus():
    return evaluation.Corpus.of(JOBS)


@pytest.fixture
def eval_set(tmp_path):
    cv = tmp_path / "cv.md"
    cv.write_text("Ingénieur IA : Python, LLM, RAG, SQL", encoding="utf-8")
    return evaluation.new_set(tmp_path / "eval" / "moi.json", "moi", {"cv": str(cv)})


def test_pool_union_des_top_k_plus_hasard_sans_doublon(eval_set, corpus):
    pool, drawn = evaluation.build_pool(eval_set, corpus, depth=2, n_random=1)
    assert len(pool) == len(set(pool))
    assert {"https://ex.ch/0", "https://ex.ch/1"} <= set(pool)  # le top 2 de BM25 et TF-IDF
    assert len(drawn) == 1 and drawn[0] in pool
    assert drawn[0] not in {"https://ex.ch/0", "https://ex.ch/1"}


def test_pool_garde_les_offres_et_le_hasard_deja_tires(eval_set, corpus):
    eval_set.pool, eval_set.drawn = ["https://ex.ch/5"], ["https://ex.ch/5"]
    pool, drawn = evaluation.build_pool(eval_set, corpus, depth=1, n_random=0)
    assert "https://ex.ch/5" in pool and drawn == ["https://ex.ch/5"]


def test_relancer_le_pooling_ne_rajoute_rien(eval_set, corpus):
    eval_set.pool, eval_set.drawn = evaluation.build_pool(eval_set, corpus, depth=2, n_random=1)
    assert evaluation.build_pool(eval_set, corpus, depth=2, n_random=1) == (
        eval_set.pool, eval_set.drawn)


def test_evaluate_un_score_par_methode_et_requete(eval_set, corpus):
    eval_set.judgments = {"https://ex.ch/1": 2, "https://ex.ch/0": 1, "https://ex.ch/4": 0}
    scores = {s.run: s for s in evaluation.evaluate(eval_set, corpus, k=2)}
    assert set(scores) == {f"{m} · cv" for m in evaluation.METHODS}
    bm25 = scores["bm25 · cv"]
    assert bm25.precision == pytest.approx(1.0) and bm25.ndcg == pytest.approx(1.0)
    assert bm25.mrr == pytest.approx(1.0) and bm25.judged == pytest.approx(1.0)


def test_plancher_du_hasard_mesure_sur_les_offres_tirees(eval_set):
    eval_set.drawn = ["https://ex.ch/3", "https://ex.ch/4", "https://ex.ch/5"]
    eval_set.judgments = {"https://ex.ch/3": 0, "https://ex.ch/4": 1}  # la 5 pas encore notée
    n, counts = evaluation.random_baseline(eval_set)
    assert n == 2 and counts == {0: 1, 1: 1}


def test_sauvegarde_et_relecture(eval_set):
    eval_set.judgments, eval_set.drawn = {"https://ex.ch/1": 2}, ["https://ex.ch/4"]
    eval_set.save()
    data = json.loads(eval_set.path.read_text(encoding="utf-8"))
    assert data["judgments"] == {"https://ex.ch/1": 2} and data["random"] == ["https://ex.ch/4"]
    (loaded,) = evaluation.load_sets([eval_set.path.parent])
    assert loaded.person == "moi" and loaded.drawn == ["https://ex.ch/4"]


def test_un_json_qui_n_est_pas_un_jeu_est_ignore(eval_set):
    eval_set.save()
    (eval_set.path.parent / "notes.json").write_text('{"https://ex.ch/1": 2}', encoding="utf-8")
    assert [s.person for s in evaluation.load_sets([eval_set.path.parent])] == ["moi"]


def test_notes_hors_echelle_refusees():
    assert evaluation.validate_grades({"u": 2, "v": 0}) == {"u": 2, "v": 0}
    with pytest.raises(ValueError, match="hors de l'échelle"):
        evaluation.validate_grades({"u": 3})
    with pytest.raises(ValueError):
        evaluation.validate_grades({"u": "oui"})


def test_page_d_annotation_autonome_et_sure():
    job = {**JOBS[0], "title": "</script><b>x</b>"}
    page = annotation.render("moi", [job], {job["url"]: 2})
    assert "</script><b>" not in page            # le JSON embarqué ne ferme pas le script
    assert '"https://ex.ch/0": 2' in page        # note existante pré-remplie
    assert "http" not in page.split("<script>")[0].split("<style>")[0]  # aucune ressource externe


def test_notes_du_navigateur_propres_a_chaque_version_de_la_page():
    """Une page régénérée après un import ne relit pas les anciennes notes du navigateur."""
    def key(judgments):
        page = annotation.render("moi", JOBS[:2], judgments)
        return page.split('const KEY = "')[1].split('"')[0]

    assert key({}) == key({})
    assert key({}) != key({"https://ex.ch/0": 2})
