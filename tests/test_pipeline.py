from datetime import datetime

import pytest

from job_rec_ai import pipeline, storage
from job_rec_ai.models import Job

COMPANIES = [
    {"company": "Acme", "sector": "Industrie", "canton": "GE", "careers_url": None,
     "ats": "workday", "board": "https://acme.wd3.myworkdayjobs.com/Acme_Careers"},
    {"company": "Acme Recherche", "sector": "Recherche", "canton": "GE", "careers_url": None,
     "ats": "smartrecruiters", "board": "ACME"},
    {"company": "Panne SA", "sector": "Banque", "canton": "GE", "careers_url": None,
     "ats": "workday", "board": "https://panne.wd1.myworkdayjobs.com/Careers"},
    {"company": "Inconnue SA", "sector": "Banque", "canton": "GE", "careers_url": None,
     "ats": "successfactors", "board": None},
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


def test_rederive(con):
    storage.upsert_jobs(con, [pipeline.enrich(_job(1, "Data Engineer"))], datetime(2026, 10, 1))
    con.execute("UPDATE jobs SET family = 'Autre', canton = NULL")
    assert pipeline.rederive(con) == 1
    assert storage.counts(con, "family") == [("Data & IA", 1)]
    assert storage.counts(con, "canton") == [("GE", 1)]


def test_replay_rejoue_aussi_les_expirations(con, tmp_path):
    def payload(day, ids):
        return {"ats": "smartrecruiters", "company": "Acme", "board": "ACME",
                "fetched_at": f"2026-10-0{day}T06:00:00+00:00",
                "postings": [{"id": i, "name": f"Analyste {i}", "location": {"city": "Genève"}}
                             for i in ids]}

    pipeline.save_raw(payload(1, ["1", "2"]), tmp_path)
    pipeline.save_raw(payload(2, ["2"]), tmp_path)  # l'offre 1 a disparu le 2 octobre
    assert pipeline.replay(con, raw_dir=tmp_path) == 3
    assert storage.totals(con) == (1, 2)


def test_boards_verifies_par_les_collectes(con, client, tmp_path):
    pipeline.crawl(con, [dict(c) for c in COMPANIES], client, raw_dir=tmp_path)
    assert storage.verified_companies(con) == {"Acme", "Acme Recherche"}


def _payload(ids, at="2026-10-02T06:00:00+00:00"):
    return {"ats": "smartrecruiters", "company": "Acme", "board": "ACME", "fetched_at": at,
            "postings": [{"id": i, "name": f"Analyste {i}", "location": {"city": "Genève"}}
                         for i in ids]}


def test_alerte_collecte_vide(con):
    pipeline.ingest(con, _payload(["1", "2"], at="2026-10-01T06:00:00+00:00"))
    result = pipeline.ingest(con, _payload([]))  # l'ATS ne renvoie plus rien
    assert (result.loaded, result.expired, result.suspect) == (0, 2, True)
    assert _count(con, "active") == 0  # on s'aligne quand même sur la source


def test_alerte_disparition_massive_puis_retour(con):
    ids = [str(i) for i in range(10)]
    pipeline.ingest(con, _payload(ids, at="2026-10-01T06:00:00+00:00"))
    result = pipeline.ingest(con, _payload(ids[:3]))  # 7 sur 10 : suspect
    assert (result.expired, result.suspect) == (7, True)
    # C'était une panne : tout revient le lendemain, avec la date d'apparition d'origine
    result = pipeline.ingest(con, _payload(ids, at="2026-10-03T06:00:00+00:00"))
    assert (result.expired, result.suspect) == (0, False)
    assert _count(con, "active AND first_seen = TIMESTAMP '2026-10-01 06:00:00'") == 10


@pytest.mark.parametrize(("missing", "active", "loaded", "suspect"), [
    (0, 10, 10, False),  # rien ne disparaît
    (2, 10, 8, False),   # retraits ordinaires
    (6, 10, 4, True),    # plus de la moitié, et au moins MIN_SUSPECT
    (3, 4, 1, False),    # petite entreprise : 3 sur 4 reste plausible
    (3, 3, 0, True),     # plus rien du tout : toujours suspect
])
def test_expiration_is_suspect(missing, active, loaded, suspect):
    assert pipeline.expiration_is_suspect(missing, active, loaded) is suspect


def test_bronze_une_archive_par_collecte(tmp_path):
    pipeline.save_raw(_payload(["1"], at="2026-10-02T06:00:00+00:00"), tmp_path)
    pipeline.save_raw(_payload(["1"], at="2026-10-02T18:30:05+00:00"), tmp_path)
    names = sorted(p.name for p in tmp_path.glob("*/*.json.gz"))
    assert names == ["smartrecruiters__acme__060000.json.gz",
                     "smartrecruiters__acme__183005.json.gz"]


def test_crawl_signale_les_suspects(con, client, tmp_path, monkeypatch):
    # Deux collectes à heures fixes (le vrai fetch horodate à la seconde : trop serré ici)
    payloads = iter([_payload(["1", "2"], at="2026-10-01T06:00:00+00:00"), _payload([])])
    monkeypatch.setattr(pipeline, "fetch_company", lambda company, client: next(payloads))
    companies = [{**COMPANIES[1], "company": "Acme"}]
    assert pipeline.crawl(con, companies, client, raw_dir=tmp_path).suspect == []
    assert pipeline.crawl(con, companies, client, raw_dir=tmp_path).suspect == [("Acme", 2)]
    assert storage.failing_companies(con) == [
        ("Acme", "smartrecruiters", "suspect", "2 offres disparues d'un coup")]


def test_quality(con):
    rows = [pipeline.enrich(_job(1)), pipeline.enrich(_job(2))]
    rows[1]["description"] = ""
    storage.upsert_jobs(con, rows, datetime(2026, 10, 1))
    (q,) = storage.quality(con)
    assert (q["source"], q["active"]) == ("workday", 2)
    assert (q["empty_description"], q["short_description"]) == (0.5, 1.0)
    assert q["no_date"] == 1.0 and q["no_canton"] == 0.0
