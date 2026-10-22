from datetime import datetime

import pytest

from job_rec_ai import pipeline, storage
from job_rec_ai.models import Job

COMPANIES = [
    {"company": "Acme", "sector": "Industrie", "canton": "GE", "careers_url": None,
     "ats": "workday", "board": "https://acme.wd3.myworkdayjobs.com/Acme_Careers",
     "verified": False},
    {"company": "Acme Recherche", "sector": "Recherche", "canton": "GE", "careers_url": None,
     "ats": "smartrecruiters", "board": "ACME", "verified": False},
    {"company": "Panne SA", "sector": "Banque", "canton": "GE", "careers_url": None,
     "ats": "workday", "board": "https://panne.wd1.myworkdayjobs.com/Careers",
     "verified": False},
    {"company": "Inconnue SA", "sector": "Banque", "canton": "GE", "careers_url": None,
     "ats": "successfactors", "board": None, "verified": False},
]


@pytest.fixture
def con():
    c = storage.connect(":memory:")
    yield c
    c.close()


def _count(con, where="TRUE"):
    return con.execute(f"SELECT count(*) FROM jobs WHERE {where}").fetchone()[0]


def test_crawl_isole_les_pannes(con, client, tmp_path):
    report = pipeline.crawl(con, [dict(c) for c in COMPANIES], client, raw_dir=tmp_path)
    assert [name for name, *_ in report.ok] == ["Acme", "Acme Recherche"]
    assert [name for name, _ in report.errors] == ["Panne SA"]
    assert report.skipped == [("Inconnue SA", "pas de connecteur « successfactors »")]
    assert _count(con) == 3
    assert len(list(tmp_path.glob("*/*.json.gz"))) == 2  # bronze archivé


def test_crawl_idempotent(con, client, tmp_path):
    companies = [dict(c) for c in COMPANIES[:2]]
    pipeline.crawl(con, companies, client, raw_dir=tmp_path)
    first = con.execute("SELECT url, first_seen FROM jobs ORDER BY url").fetchall()
    pipeline.crawl(con, companies, client, raw_dir=tmp_path)
    second = con.execute("SELECT url, first_seen FROM jobs ORDER BY url").fetchall()
    assert first == second  # mêmes offres, et first_seen n'a pas bougé


def test_enrichissement(con, client, tmp_path):
    pipeline.crawl(con, [dict(c) for c in COMPANIES[:2]], client, raw_dir=tmp_path)
    row = storage.search(con, company="acme recherche")[0]
    assert row["canton"] == "GE" and row["language"] == "fr"
    assert row["family"] == "Data & IA" and row["sector"] == "Recherche"
    compta = storage.search(con, text="comptable")[0]
    assert (compta["canton"], compta["workload_min"], compta["workload_max"]) == ("VD", 80, 100)


def _job(n, title="Data Engineer"):
    return Job(title=title, company="Acme", url=f"https://acme.example/jobs/{n}",
               location="Genève", description="Pipelines.", source="workday")


def test_expiration_seulement_apres_succes(con):
    t1, t2 = datetime(2026, 10, 1), datetime(2026, 10, 2)
    storage.upsert_jobs(con, [pipeline.enrich(_job(1)), pipeline.enrich(_job(2))], t1)
    storage.upsert_jobs(con, [pipeline.enrich(_job(2))], t2)
    assert storage.expire_missing(con, "Acme", "workday", t2) == 1
    assert _count(con, "active") == 1
    # L'offre 1 réapparaît : elle redevient active, avec sa date d'apparition d'origine
    storage.upsert_jobs(con, [pipeline.enrich(_job(1))], datetime(2026, 10, 3))
    assert con.execute("SELECT active, first_seen FROM jobs WHERE url LIKE '%/1'").fetchone() \
        == (True, t1)


def test_search_facettes_et_tri(con):
    rows = [pipeline.enrich(_job(1, "Data Engineer")), pipeline.enrich(_job(2, "Comptable")),
            pipeline.enrich(_job(3, "Stagiaire Data"))]
    storage.upsert_jobs(con, rows, datetime(2026, 10, 1))
    assert {r["title"] for r in storage.search(con, family="data & ia")} == \
        {"Data Engineer", "Stagiaire Data"}
    assert [r["title"] for r in storage.search(con, seniority="Stage / Apprentissage")] == \
        ["Stagiaire Data"]
    assert [r["title"] for r in storage.search(con, sort="title")] == \
        ["Comptable", "Data Engineer", "Stagiaire Data"]
    with pytest.raises(ValueError):
        storage.search(con, salaire="100k")
    assert dict(storage.counts(con, "family"))["Data & IA"] == 2


def test_replay_reconstruit_la_base(con, client, tmp_path):
    pipeline.crawl(con, [dict(c) for c in COMPANIES[:2]], client, raw_dir=tmp_path)
    fresh = storage.connect(":memory:")
    assert pipeline.replay(fresh, raw_dir=tmp_path) == 3
    assert _count(fresh) == 3


def test_reclassify(con):
    storage.upsert_jobs(con, [pipeline.enrich(_job(1, "Data Engineer"))], datetime(2026, 10, 1))
    con.execute("UPDATE jobs SET family = 'Autre'")
    assert pipeline.reclassify(con) == 1
    assert storage.counts(con, "family") == [("Data & IA", 1)]
