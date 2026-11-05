import json

import pytest

from job_rec_ai import annotation, evaluation

JOBS = [{"url": f"https://ex.ch/{i}", "title": t, "company": "Acme", "description": d}
        for i, (t, d) in enumerate([
            ("Data Engineer", "Python, SQL, dbt, Airflow."),
            ("Développeur IA", "LLM, RAG, Python, agents."),
            ("Comptable", "Comptabilité fournisseurs, SAP."),
            ("Infirmier", "Soins intensifs, nuit."),
            ("Boulanger", "Pain, viennoiseries."),
            ("Juriste", "Droit des contrats."),
        ])]


@pytest.fixture
def eval_set(tmp_path):
    cv = tmp_path / "cv.md"
    cv.write_text("Ingénieur IA : Python, LLM, RAG, SQL", encoding="utf-8")
    return evaluation.new_set(tmp_path / "eval" / "moi.json", "moi", {"cv": str(cv)})


def test_pool_union_des_top_k_plus_hasard_sans_doublon(eval_set):
    pool = evaluation.build_pool(eval_set, JOBS, depth=2, n_random=1)
    assert len(pool) == len(set(pool))
    assert {"https://ex.ch/0", "https://ex.ch/1"} <= set(pool)  # le top 2 de BM25 et TF-IDF
    assert 3 <= len(pool) <= 2 * 3 + 1


def test_pool_garde_les_offres_deja_jugees(eval_set):
    eval_set.pool = ["https://ex.ch/5"]
    assert "https://ex.ch/5" in evaluation.build_pool(eval_set, JOBS, depth=1, n_random=0)


def test_evaluate_un_score_par_methode_et_requete(eval_set):
    eval_set.judgments = {"https://ex.ch/1": 2, "https://ex.ch/0": 1, "https://ex.ch/4": 0}
    scores = {s.run: s for s in evaluation.evaluate(eval_set, JOBS, k=2)}
    assert set(scores) == {f"{m} · cv" for m in evaluation.METHODS}
    bm25 = scores["bm25 · cv"]
    assert bm25.precision == pytest.approx(1.0) and bm25.ndcg == pytest.approx(1.0)
    assert bm25.mrr == pytest.approx(1.0) and bm25.judged == pytest.approx(1.0)


def test_sauvegarde_et_relecture(eval_set):
    eval_set.judgments = {"https://ex.ch/1": 2}
    eval_set.save()
    data = json.loads(eval_set.path.read_text(encoding="utf-8"))
    assert data["judgments"] == {"https://ex.ch/1": 2}
    (loaded,) = evaluation.load_sets([eval_set.path.parent])
    assert loaded.person == "moi" and loaded.judgments == {"https://ex.ch/1": 2}


def test_page_d_annotation_autonome_et_sure():
    job = {**JOBS[0], "title": "</script><b>x</b>"}
    page = annotation.render("moi", [job], {job["url"]: 2})
    assert "</script><b>" not in page            # le JSON embarqué ne ferme pas le script
    assert '"https://ex.ch/0": 2' in page        # note existante pré-remplie
    assert "http" not in page.split("<script>")[0].split("<style>")[0]  # aucune ressource externe
