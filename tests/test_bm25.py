import math

import pytest

from job_rec_ai.bm25 import BM25
from job_rec_ai.recommend import query_terms, rank


def test_idf_toujours_positif_et_decroissant():
    bm = BM25([["et", "python"], ["et", "sql"], ["et", "rag"]])
    assert bm.idf("et") == pytest.approx(math.log(1 + 0.5 / 3.5))  # partout, mais > 0
    assert bm.idf("python") > bm.idf("et")
    assert bm.idf("absent") > bm.idf("python")


def test_saturation_le_poids_plafonne_a_k1_plus_1():
    """Même longueur partout (b sans effet) : 100 mentions ne valent pas 100 fois une."""
    docs = [["rag"] + ["x"] * 99, ["rag"] * 100, ["y"] * 100]
    bm = BM25(docs, k1=1.2)
    one, hundred, _ = bm.scores(["rag"])
    assert one < hundred < (1.2 + 1) * bm.idf("rag")
    assert hundred / one < 2.5


def test_normalisation_de_longueur():
    """Une mention dans une offre courte pèse plus que dans une longue, sauf si b = 0."""
    docs = [["rag", "a"], ["rag"] + ["b"] * 20]
    short, long_ = BM25(docs, b=0.75).scores(["rag"])
    assert short > long_
    short, long_ = BM25(docs, b=0).scores(["rag"])
    assert short == pytest.approx(long_)


def test_requete_sans_mots_outils_ni_doublons():
    assert query_terms("Python et SQL, python et dbt") == ["python", "sql", "dbt"]
    assert query_terms("Python et python", unique=False) == ["python", "python"]


def test_rank_classe_l_offre_la_plus_proche_en_tete():
    jobs = [{"title": "Comptable", "description": "Comptabilité fournisseurs, SAP."},
            {"title": "Data Engineer", "description": "Python, SQL, dbt et Airflow."},
            {"title": "Infirmier", "description": "Soins intensifs."}]
    ranked = rank(jobs, "Ingénieur data : Python, dbt, SQL")
    assert ranked[0]["title"] == "Data Engineer"
    assert ranked[0]["score"] > ranked[1]["score"] >= 0
