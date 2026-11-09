"""Routes /jobs de l'API (pages publiques d'offres de DoxAI), l'`id` de /recommend, la
migration de la colonne description_markdown et son remplissage depuis les archives."""

import gzip
import hashlib
import json
from datetime import date, datetime, timedelta
from pathlib import Path

import duckdb
import pytest
from fastapi.testclient import TestClient

from job_rec_ai import api, catalog, pipeline, storage
from job_rec_ai.connectors import REGISTRY
from job_rec_ai.models import Job

FIXTURES = Path(__file__).parent / "fixtures"
TODAY = date.today()
LONG = ("Comptabilité fournisseurs, SAP, clôtures mensuelles et reporting pour un groupe "
        "international en pleine croissance. Vous préparez les bouclements, suivez les "
        "paiements et améliorez les processus avec l'équipe finance, dans un environnement "
        "exigeant et bienveillant au cœur de Genève.")

# (titre, entreprise, lieu, description, publiée il y a n jours, taux min, taux max, Markdown)
OFFERS = [
    ("Data Engineer", "Acme", "Genève", "Python, SQL, dbt et Airflow pour la plateforme data.",
     2, 80, 100, "## Missions\n\n- Python\n- SQL"),
    ("Développeur IA", "Beta", "Lausanne", "LLM, RAG, agents et Python en production.",
     10, 100, 100, None),
    ("Comptable", "Acme", "Genève", LONG, None, 40, 60, None),
    ("Data Analyst", "Gamma", "Fribourg", "Python, SQL, tableaux de bord Power BI.",
     40, None, None, None),
    ("Pflegefachperson", "Delta", "Neuchâtel",
     "Wir suchen eine Pflegefachperson für die Station und das Team mit Erfahrung.",
     1, 50, 80, None),
]


def _url(i: int) -> str:
    return f"https://ats.example/jobs/{i}"


def _write_db(path, offers=OFFERS):
    con = storage.connect(path)
    rows = []
    for i, (title, company, place, text, days, low, high, md) in enumerate(offers):
        job = Job(title=title, company=company, url=_url(i), location=place, description=text,
                  source="workday", description_markdown=md,
                  posted_at=TODAY - timedelta(days=days) if days is not None else None)
        rows.append({**pipeline.enrich(job), "workload_min": low, "workload_max": high})
    storage.upsert_jobs(con, rows, datetime.now() - timedelta(hours=1))
    con.close()


def _id(i: int) -> str:
    return hashlib.sha256(_url(i).encode()).hexdigest()[:16]


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


def _titles(body) -> list[str]:
    return [j["title"] for j in body["jobs"]]


# --- authentification -----------------------------------------------------------------------

def test_jeton_exige_sur_toutes_les_routes_jobs(db, monkeypatch):
    monkeypatch.setenv("JOB_REC_TOKEN", "secret")
    with TestClient(api.create_app(db)) as c:
        for route in ("/jobs", f"/jobs/{_id(0)}", f"/jobs/{_id(0)}/similar"):
            assert c.get(route).status_code == 401
            assert c.get(route, headers={"Authorization": "Bearer faux"}).status_code == 401
            ok = c.get(route, headers={"Authorization": "Bearer secret"})
            assert ok.status_code == 200, route
        assert c.get("/health").status_code == 200


# --- GET /jobs ------------------------------------------------------------------------------

def test_liste_par_defaut_les_plus_recentes_sans_date_a_la_fin(client):
    body = client.get("/jobs").json()
    assert body["total"] == 5 and body["page"] == 1 and body["per_page"] == 20
    assert _titles(body) == ["Pflegefachperson", "Data Engineer", "Développeur IA",
                             "Data Analyst", "Comptable"]
    assert body["facets"] == {"cantons": {"GE": 2, "FR": 1, "NE": 1, "VD": 1}}


def test_forme_d_un_job_summary(client):
    job = client.get("/jobs").json()["jobs"][1]
    assert job == {
        "id": _id(0), "url": _url(0), "title": "Data Engineer", "company": "Acme",
        "company_domain": None,
        "location": "Genève", "canton": "GE", "workload_min": 80, "workload_max": 100,
        "posted_at": (TODAY - timedelta(days=2)).isoformat(), "language": "fr",
        "employment_type": None, "family": job["family"],
        "snippet": "Python, SQL, dbt et Airflow pour la plateforme data."}
    langues = {j["title"]: j["language"] for j in client.get("/jobs").json()["jobs"]}
    assert langues["Pflegefachperson"] == "de"  # « other » en base, précisé pour l'API


def test_recherche_plein_texte_bm25(client):
    body = client.get("/jobs", params={"q": "Python SQL"}).json()
    assert set(_titles(body)) == {"Data Engineer", "Data Analyst", "Développeur IA"}
    assert _titles(body)[-1] == "Développeur IA"  # un seul des deux mots : classé dernier
    # L'entreprise est cherchée aussi ; un mot absent partout ne renvoie rien
    assert _titles(client.get("/jobs", params={"q": "gamma"}).json()) == ["Data Analyst"]
    assert client.get("/jobs", params={"q": "boulanger"}).json()["total"] == 0


def test_tri_recent_force_avec_une_recherche(client):
    body = client.get("/jobs", params={"q": "python sql", "sort": "recent"}).json()
    assert _titles(body) == ["Data Engineer", "Développeur IA", "Data Analyst"]


def test_filtre_cantons_et_facettes_sans_ce_filtre(client):
    body = client.get("/jobs", params={"cantons": "GE, vd"}).json()
    assert set(_titles(body)) == {"Data Engineer", "Comptable", "Développeur IA"}
    assert body["total"] == 3
    # Les facettes comptent tous les cantons : on peut élargir sa recherche
    assert body["facets"]["cantons"] == {"GE": 2, "FR": 1, "NE": 1, "VD": 1}
    # …mais elles suivent les autres filtres
    body = client.get("/jobs", params={"q": "python", "cantons": "GE"}).json()
    assert _titles(body) == ["Data Engineer"]
    assert body["facets"]["cantons"] == {"FR": 1, "GE": 1, "VD": 1}
    # Les employeurs distincts parmi les résultats filtrés, pas parmi toute la base
    assert body["companies"] == 1


def test_filtre_taux_par_recouvrement_des_plages(client):
    titles = set(_titles(client.get("/jobs", params={"workload_min": 90}).json()))
    # Data Analyst n'affiche pas de taux : supposé à 100 %
    assert titles == {"Data Engineer", "Développeur IA", "Data Analyst"}
    titles = set(_titles(client.get("/jobs", params={"workload_max": 50}).json()))
    assert titles == {"Comptable", "Pflegefachperson"}  # 40-60 et 50-80 touchent 50
    titles = _titles(client.get("/jobs", params={"workload_min": 70, "workload_max": 75}).json())
    assert titles == ["Pflegefachperson"]


def test_filtre_par_anciennete(client):
    titles = set(_titles(client.get("/jobs", params={"posted_within_days": 7}).json()))
    # Comptable n'a pas de date de publication : sa date de première collecte (aujourd'hui)
    assert titles == {"Pflegefachperson", "Data Engineer", "Comptable"}


def test_pagination_sans_doublon_ni_trou(client):
    pages = [client.get("/jobs", params={"per_page": 2, "page": p}).json() for p in (1, 2, 3, 4)]
    assert [len(p["jobs"]) for p in pages] == [2, 2, 1, 0]
    assert all(p["total"] == 5 and p["per_page"] == 2 for p in pages)
    ids = [j["id"] for p in pages for j in p["jobs"]]
    assert sorted(ids) == sorted(_id(i) for i in range(5))


@pytest.mark.parametrize("params", [{"per_page": 51}, {"per_page": 0}, {"page": 0},
                                    {"sort": "salaire"}, {"workload_min": 101},
                                    {"workload_min": 80, "workload_max": 50}])
def test_parametres_invalides(client, params):
    assert client.get("/jobs", params=params).status_code == 422


def test_extrait_coupe_sur_un_mot(client):
    comptable = next(j for j in client.get("/jobs").json()["jobs"] if j["title"] == "Comptable")
    assert len(comptable["snippet"]) <= 240 and comptable["snippet"].endswith("…")
    assert LONG.startswith(comptable["snippet"][:-1])
    assert LONG[len(comptable["snippet"]) - 1] == " "  # le mot suivant n'est pas entamé


# --- GET /jobs/{id} ---------------------------------------------------------------------------

def test_detail_d_une_offre(client):
    job = client.get(f"/jobs/{_id(0)}").json()
    assert job["description_markdown"] == "## Missions\n\n- Python\n- SQL"
    assert job["description_text"] == "Python, SQL, dbt et Airflow pour la plateforme data."
    assert job["source"] == "workday" and job["seniority"] and "category" in job
    summary = client.get("/jobs").json()["jobs"][1]
    assert {k: job[k] for k in summary} == summary
    assert set(job) == set(summary) | {"description_markdown", "description_text", "category",
                                       "seniority", "source"}


def test_detail_sans_markdown_en_base_paragraphes_du_texte(client):
    job = client.get(f"/jobs/{_id(1)}").json()
    assert job["description_markdown"] == "LLM, RAG, agents et Python en production."


@pytest.mark.parametrize("job_id", ["0123456789abcdef", "pas-un-id", _id(0).upper()])
def test_offre_inconnue_404(client, job_id):
    for route in (f"/jobs/{job_id}", f"/jobs/{job_id}/similar"):
        response = client.get(route)
        assert response.status_code == 404 and response.json() == {"detail": "not_found"}


# --- GET /jobs/{id}/similar ---------------------------------------------------------------------

def test_offres_semblables_sans_elle_meme(client):
    similar = client.get(f"/jobs/{_id(0)}/similar").json()
    assert _id(0) not in [j["id"] for j in similar]
    assert [j["title"] for j in similar] == ["Data Analyst", "Développeur IA"]
    assert set(similar[0]) == set(client.get("/jobs").json()["jobs"][0])  # des JobSummary
    assert len(client.get(f"/jobs/{_id(0)}/similar", params={"k": 1}).json()) == 1


@pytest.mark.parametrize("k", [0, 13])
def test_semblables_k_borne(client, k):
    assert client.get(f"/jobs/{_id(0)}/similar", params={"k": k}).status_code == 422


# --- POST /recommend ----------------------------------------------------------------------------

def test_recommend_porte_l_id(client):
    reco = client.post("/recommend", json={"cv_text": "Python SQL dbt", "k": 1}).json()[0]
    assert reco["job_id"] == reco["url"] == _url(0)
    assert reco["id"] == _id(0) == catalog.job_id(reco["url"])


# Classement de /recommend sur une base faite des 13 fixtures réelles, relevé AVANT l'ajout des
# routes /jobs (main, 53bd813) : les URL des résultats, en id. Il ne doit pas bouger.
GOLDEN = {
    "Ingénieur data : Python, SQL, dbt, Airflow, machine learning": [
        "d5bf9dc5d787ba05", "6c561bd9ec638d63", "a91c08c7131d58d1", "cac14f96b7ef4dc8",
        "1dfb02448a2d64a8", "d2a99539cb5facb8", "14300dc7d0c9c6ee", "2764ba69225e462b",
        "1e334ac5d1acba6b", "fb36afd65b813816", "2399466123037450", "a6ea5136b93e0181",
        "4408324c30c5de4e", "9a9dbabdd991adbc", "3faff554b950d3ac"],
    "Comptable, finance, audit, SAP, clôtures mensuelles": [
        "8f57fcf43eba33af", "b64caa73d8d306ef", "cd734dc69ad56a15", "14300dc7d0c9c6ee",
        "10e7c2c53184d44b", "8978733a35a48b8c", "fa7d545713132d2a", "3faff554b950d3ac",
        "96595f678807712b"],
    "Software engineer, cloud, Kubernetes, security, privacy": [
        "6c561bd9ec638d63", "4408324c30c5de4e", "cac14f96b7ef4dc8", "fb36afd65b813816",
        "1dfb02448a2d64a8", "d2a99539cb5facb8", "2764ba69225e462b", "2a954b58d01f06de",
        "da832299182803e4", "3faff554b950d3ac", "946206f9ab58001e", "65c94a2a5036346c",
        "9c849d32dc1edf26", "9a9dbabdd991adbc", "a91c08c7131d58d1"],
    "Infirmier, soins, santé, hôpital": [
        "cbea446c1eec4388", "e924856125e41e70", "bfc4da0ea6ff40af", "db4bd695a8f79253",
        "3ea981f02f04b32f"],
}


def _fixtures_db(path: Path) -> Path:
    con = storage.connect(path)
    for fixture in sorted(FIXTURES.glob("*.json")):
        pipeline.ingest(con, json.loads(fixture.read_text(encoding="utf-8")))
    con.close()
    return path


def test_recommend_meme_classement_qu_avant(tmp_path, monkeypatch):
    monkeypatch.delenv("JOB_REC_TOKEN", raising=False)
    with TestClient(api.create_app(_fixtures_db(tmp_path / "jobs.duckdb"))) as c:
        for cv_text, expected in GOLDEN.items():
            recos = c.post("/recommend", json={"cv_text": cv_text, "k": 15}).json()
            assert [catalog.job_id(r["job_id"]) for r in recos] == expected, cv_text
            assert all(r["id"] == catalog.job_id(r["url"]) for r in recos)


def test_toutes_les_offres_des_fixtures_ont_une_page(tmp_path, monkeypatch):
    monkeypatch.delenv("JOB_REC_TOKEN", raising=False)
    with TestClient(api.create_app(_fixtures_db(tmp_path / "jobs.duckdb"))) as c:
        body = c.get("/jobs", params={"per_page": 50}).json()
        assert body["total"] > 40
        for summary in body["jobs"]:
            assert len(summary["snippet"]) <= 240
            assert summary["language"] in ("fr", "de", "en", "it", None)
            job = c.get(f"/jobs/{summary['id']}").json()
            assert job["description_markdown"] and "<script" not in job["description_markdown"]


# --- migration et remplissage -------------------------------------------------------------------

def _old_schema(path: Path) -> None:
    """La base telle qu'en production avant cette version : sans description_markdown."""
    view = storage.SCHEMA[storage.SCHEMA.index("CREATE OR REPLACE VIEW"):]
    with duckdb.connect(str(path)) as con:
        con.execute("DROP VIEW jobs_view")
        con.execute("ALTER TABLE jobs DROP COLUMN description_markdown")
        con.execute(view)


def test_l_api_lit_une_base_pas_encore_migree(db, monkeypatch):
    _old_schema(db)
    monkeypatch.delenv("JOB_REC_TOKEN", raising=False)
    with TestClient(api.create_app(db)) as c:  # lecture seule : elle ne peut pas migrer
        job = c.get(f"/jobs/{_id(0)}").json()
        assert job["description_markdown"] == job["description_text"]
        assert c.post("/recommend", json={"cv_text": "Python"}).status_code == 200


def test_migration_additive_sur_une_base_existante(db):
    _old_schema(db)
    con = storage.connect(db)  # ce que fait la prochaine collecte (ou backfill-markdown)
    try:
        assert storage.totals(con) == (5, 5)
        assert con.execute("SELECT count(*) FROM jobs_view WHERE description_markdown IS NULL"
                           ).fetchone() == (5,)
    finally:
        con.close()


def _archive(raw_dir: Path, payload: dict, day: str, clock: str) -> None:
    path = raw_dir / day / f"{payload['ats']}__{payload['company'].lower()}__{clock}.json.gz"
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(payload, f)


def test_backfill_depuis_la_derniere_archive_de_chaque_entreprise(tmp_path):
    payload = json.loads((FIXTURES / "greenhouse.json").read_text(encoding="utf-8"))
    con = storage.connect(tmp_path / "jobs.duckdb")
    pipeline.ingest(con, payload)
    con.execute("UPDATE jobs SET description_markdown = NULL")  # une base d'avant la colonne
    stale = {**payload, "postings": payload["postings"][:1]}
    raw = tmp_path / "raw"
    _archive(raw, stale, "2026-11-06", "031700")
    _archive(raw, payload, "2026-11-07", "031700")  # la plus récente : toutes les offres
    _archive(raw, stale, "2026-11-07", "010000")
    assert [p.parent.name for p in pipeline.latest_archives(raw)] == ["2026-11-07"]

    archives, updated = pipeline.backfill_markdown(con, raw)
    expected = {str(j.url): j.description_markdown
                for j in REGISTRY["greenhouse"].parse(payload)}
    stored = dict(con.execute("SELECT url, description_markdown FROM jobs").fetchall())
    con.close()
    assert (archives, updated) == (1, len(expected)) and stored == expected
