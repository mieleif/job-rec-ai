"""Domaine web des employeurs (logos de DoxAI) : config, normalisation, recherche logo.dev
(simulée, jamais le réseau), cache en base, et `company_domain` sur les quatre routes."""

import json
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from job_rec_ai import api, cli, domains, pipeline, storage
from job_rec_ai.companies import DEFAULT_CSV, load_companies
from job_rec_ai.models import Job

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 11, 7, 4, 0)


# --- la config ----------------------------------------------------------------------------------

def test_chaque_source_collectee_a_un_domaine_nu():
    companies = load_companies(DEFAULT_CSV)
    collected = [c for c in companies if pipeline.skip_reason(c) is None]
    assert len(collected) >= 60
    assert [c["company"] for c in collected if not c["domain"]] == []
    for c in companies:
        if c["domain"]:
            assert c["domain"] == domains.normalize_domain(c["domain"]), c["company"]
    by_name = {c["company"]: c["domain"] for c in companies}
    assert by_name["Vitol"] == "vitol.com" and by_name["Coop"] == "coop.ch"
    assert by_name["Rolex"] is None  # pas de connecteur : laissé vide


def test_domaine_invalide_dans_la_config(tmp_path):
    csv = tmp_path / "companies.csv"
    csv.write_text("company,domain\nAcme,https://www.Acme.ch/jobs\nBeta,pas un domaine\n",
                   encoding="utf-8")
    with pytest.raises(SystemExit, match="Beta"):
        load_companies(csv)
    csv.write_text("company,domain\nAcme,https://www.Acme.ch/jobs\n", encoding="utf-8")
    assert load_companies(csv)[0]["domain"] == "acme.ch"


# --- normalisation ------------------------------------------------------------------------------

@pytest.mark.parametrize("raw, expected", [
    ("vitol.com", "vitol.com"),
    ("https://www.Coop.ch/fr/jobs?x=1", "coop.ch"),
    ("WWW.EPFL.CH.", "epfl.ch"),
    ("http://user@ge.ch:443/emploi", "ge.ch"),
    ("home.cern", "home.cern"),
    ("", None), (None, None), ("coop", None), ("coop .ch", None), ("-a.ch", None),
])
def test_normalize_domain(raw, expected):
    assert domains.normalize_domain(raw) == expected


@pytest.mark.parametrize("a, b", [
    ("Nestlé S.A.", "nestle"),
    ("Procter & Gamble Co.", "Procter and Gamble"),
    ("Groupe Mutuel Sàrl", "groupe mutuel"),
    ("Acme Holding AG", "ACME"),
    ("The Global Fund", "Global Fund"),
    ("HFR (hôpital fribourgeois)", "HFR"),
    ("Coop Genossenschaft GmbH", "coop genossenschaft"),
])
def test_company_key_egales(a, b):
    assert domains.company_key(a) == domains.company_key(b)


@pytest.mark.parametrize("a, b", [("Swatch Group", "Swatch"), ("Coop", "Coop Pronto"),
                                  ("UBS", "UBP")])
def test_company_key_differentes(a, b):
    assert domains.company_key(a) != domains.company_key(b)


def test_company_key_d_une_forme_juridique_seule():
    assert domains.company_key("SA") == "sa"


def test_requete_sans_parentheses():
    assert domains.search_query("BNP Paribas (Suisse)") == "BNP Paribas"


# --- choix d'un candidat ------------------------------------------------------------------------

def test_match_sur():
    candidates = [{"name": "Vitol Group", "domain": "vitolgroup.com"},
                  {"name": "Vitol SA", "domain": "https://www.vitol.com/"}]
    assert domains.pick("Vitol", candidates) == "vitol.com"


def test_ambigu_ou_sans_match_donne_none():
    assert domains.pick("Acme", [{"name": "Acme", "domain": "acme.com"},
                                 {"name": "ACME Inc.", "domain": "acme.io"}]) is None
    assert domains.pick("Acme", [{"name": "Acme Robotics", "domain": "acmerobotics.com"}]) is None
    assert domains.pick("Acme", []) is None
    assert domains.pick("Acme", [{"name": "Acme", "domain": "pas un domaine"}]) is None


def test_egalite_departagee_par_le_ch():
    candidates = [{"name": "Coop", "domain": "coop.se"}, {"name": "Coop", "domain": "coop.ch"},
                  {"name": "Coop", "domain": "coop.co.uk"}]
    assert domains.pick("Coop", candidates) == "coop.ch"
    candidates.append({"name": "Coop", "domain": "coop-genossenschaft.ch"})
    assert domains.pick("Coop", candidates) is None  # deux .ch : toujours ambigu


def test_meme_domaine_plusieurs_fois():
    assert domains.pick("Acme", [{"name": "Acme", "domain": "acme.ch"},
                                 {"name": "Acme AG", "domain": "www.acme.ch"}]) == "acme.ch"


# --- le client logo.dev (transport simulé) ------------------------------------------------------

def _client(handler, sleeps=None):
    sleeps = [] if sleeps is None else sleeps
    return domains.BrandSearch("sk_test", delay=0.5, transport=httpx.MockTransport(handler),
                               sleep=sleeps.append)


def test_recherche_v2_avec_la_cle_secrete():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"data": [{"object": "search_result", "name": "Vitol",
                                                   "domain": "vitol.com"}],
                                         "metadata": {"request_id": "r"}})

    with _client(handler) as search:
        assert search.search("Vitol (Genève)") == [
            {"object": "search_result", "name": "Vitol", "domain": "vitol.com"}]
    assert seen[0].url.host == "api.logo.dev" and seen[0].url.path == "/v2/search"
    assert seen[0].url.params["q"] == "Vitol"
    assert seen[0].headers["Authorization"] == "Bearer sk_test"


def test_reponse_v1_en_liste_acceptee():
    with _client(lambda r: httpx.Response(200, json=[{"name": "A", "domain": "a.ch"}])) as s:
        assert s.search("A") == [{"name": "A", "domain": "a.ch"}]


def test_erreur_serveur_reessayee_une_fois():
    calls, sleeps = [], []

    def handler(request):
        calls.append(1)
        return httpx.Response(503) if len(calls) == 1 else httpx.Response(200, json={"data": []})

    with _client(handler, sleeps) as search:
        assert search.search("Acme") == []
    assert len(calls) == 2 and sleeps  # une pause avant le nouvel essai


def test_echec_persistant_puis_erreur():
    calls = []

    def handler(request):
        calls.append(1)
        raise httpx.ConnectTimeout("lent")

    with _client(handler) as search, pytest.raises(domains.SearchError):
        search.search("Acme")
    assert len(calls) == 2  # un seul nouvel essai


def test_429_attend_le_delai_annonce():
    calls, sleeps = [], []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, headers={"RateLimit-Reset": "7"})
        return httpx.Response(200, json={"data": []})

    with _client(handler, sleeps) as search:
        search.search("Acme")
    assert 7.0 in sleeps


def test_cle_refusee_sans_nouvel_essai():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(401, json={"msg": "invalid key"})

    with _client(handler) as search, pytest.raises(domains.AuthError):
        search.search("Acme")
    assert len(calls) == 1


def test_sans_cle_pas_de_client(monkeypatch):
    monkeypatch.delenv(domains.ENV_KEY, raising=False)
    assert domains.BrandSearch.from_env() is None
    monkeypatch.setenv(domains.ENV_KEY, "  ")
    assert domains.BrandSearch.from_env() is None


# --- la résolution et son cache -----------------------------------------------------------------

class FakeSearch:
    """Réponses par nom ; une exception dans la table est levée à l'appel."""

    def __init__(self, answers):
        self.answers, self.calls = answers, []

    def search(self, name):
        self.calls.append(name)
        answer = self.answers[name]
        if isinstance(answer, Exception):
            raise answer
        return answer


def _db(tmp_path, companies=("Acme", "Beta", "Gamma", "Delta")):
    con = storage.connect(tmp_path / "jobs.duckdb")
    rows = [pipeline.enrich(Job(title="Data Engineer", company=name,
                                url=f"https://ats.example/{i}", location="Genève",
                                description="Python et SQL.", source="workday"))
            for i, name in enumerate(companies)]
    storage.upsert_jobs(con, rows, NOW - timedelta(hours=1))
    return con


def _domains(con):
    return {row["company"]: row["domain"] for row in storage.domain_cache(con).values()}


SEARCH_ANSWERS = {
    "Beta": [{"name": "Beta SA", "domain": "beta.ch"}],                     # match sûr
    "Gamma": [{"name": "Gamma", "domain": "gamma.com"},
              {"name": "Gamma", "domain": "gamma.io"}],                     # ambigu
    "Delta": domains.SearchError("HTTP 503"),                               # API en panne
}


def test_config_puis_recherche(tmp_path):
    con = _db(tmp_path)
    search = FakeSearch(SEARCH_ANSWERS)
    result = domains.resolve(con, [{"company": "Acme", "domain": "acme.ch"}], {}, search, NOW)
    assert sorted(search.calls) == ["Beta", "Delta", "Gamma"]  # pas Acme : la config suffit
    assert _domains(con) == {"Acme": "acme.ch", "Beta": "beta.ch", "Gamma": None}
    assert result.fixed == 1 and result.found == [("Beta", "beta.ch")]
    assert result.not_found == ["Gamma"] and [n for n, _ in result.errors] == ["Delta"]


def test_cache_reutilise_et_erreur_reessayee(tmp_path):
    con = _db(tmp_path, ("Beta", "Gamma", "Delta"))
    domains.resolve(con, [], {}, FakeSearch(SEARCH_ANSWERS), NOW)
    again = FakeSearch({**SEARCH_ANSWERS, "Delta": [{"name": "Delta", "domain": "delta.ch"}]})
    result = domains.resolve(con, [], {}, again, NOW + timedelta(days=1))
    assert again.calls == ["Delta"]  # Beta (trouvé) et Gamma (null récent) viennent du cache
    assert result.reused == 2 and _domains(con)["Delta"] == "delta.ch"


def test_null_reverifie_apres_30_jours(tmp_path):
    con = _db(tmp_path, ("Gamma",))
    domains.resolve(con, [], {}, FakeSearch(SEARCH_ANSWERS), NOW)
    later = FakeSearch({"Gamma": [{"name": "Gamma", "domain": "gamma.com"}]})
    domains.resolve(con, [], {}, later, NOW + timedelta(days=29))
    assert later.calls == []
    domains.resolve(con, [], {}, later, NOW + timedelta(days=31))
    assert later.calls == ["Gamma"] and _domains(con) == {"Gamma": "gamma.com"}


def test_sans_cle_recherche_sautee(tmp_path):
    con = _db(tmp_path)
    result = domains.resolve(con, [{"company": "Acme", "domain": "acme.ch"}], {}, None, NOW)
    assert _domains(con) == {"Acme": "acme.ch"}  # la config, sans réseau
    assert sorted(result.skipped) == ["Beta", "Delta", "Gamma"] and not result.errors


def test_cle_refusee_arrete_la_recherche(tmp_path):
    con = _db(tmp_path, ("Beta", "Gamma"))
    search = FakeSearch({"Beta": domains.AuthError("HTTP 401"), "Gamma": []})
    result = domains.resolve(con, [], {}, search, NOW)
    assert search.calls == ["Beta"] and len(result.errors) == 2
    assert _domains(con) == {}  # rien en cache : réessayé à la prochaine collecte


def test_override_gagne_sur_config_et_recherche(tmp_path):
    con = _db(tmp_path)
    domains.resolve(con, [{"company": "Acme", "domain": "acme.ch"}], {},
                    FakeSearch(SEARCH_ANSWERS), NOW)
    path = tmp_path / domains.OVERRIDES_NAME
    path.write_text("company,domain,reason\nAcme,acme-group.com,logo du groupe\n"
                    "Beta SA,,mauvais match\n", encoding="utf-8")
    overrides = domains.load_overrides(path)
    search = FakeSearch(SEARCH_ANSWERS)
    domains.resolve(con, [{"company": "Acme", "domain": "acme.ch"}], overrides, search, NOW)
    assert "Beta" not in search.calls
    assert _domains(con)["Acme"] == "acme-group.com"
    assert _domains(con)["Beta SA"] is None  # forcé à « pas de logo »


def test_override_ou_config_retire_repasse_a_la_recherche(tmp_path):
    con = _db(tmp_path, ("Beta",))
    domains.resolve(con, [{"company": "Beta", "domain": "beta.com"}], {}, None, NOW)
    search = FakeSearch(SEARCH_ANSWERS)
    domains.resolve(con, [{"company": "Beta", "domain": None}], {}, search, NOW)
    assert search.calls == ["Beta"] and _domains(con) == {"Beta": "beta.ch"}


def test_overrides_absents_ou_invalides(tmp_path):
    assert domains.load_overrides(tmp_path / "absent.csv") == {}
    path = tmp_path / domains.OVERRIDES_NAME
    path.write_text("company,domain\nAcme,pas un domaine\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="Acme"):
        domains.load_overrides(path)


def test_commande_resolve_domains_sans_cle(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv(domains.ENV_KEY, raising=False)
    db = tmp_path / "jobs.duckdb"
    _db(tmp_path, ("Vitol", "Inconnue SA")).close()
    cli.main(["--db", str(db), "--companies", str(DEFAULT_CSV), "resolve-domains"])
    out = capsys.readouterr().out
    assert "recherche sautée" in out and "1 entreprise(s)" in out
    con = storage.connect(db)
    assert _domains(con)["Vitol"] == "vitol.com"
    con.close()


# --- l'API : company_domain sur les quatre routes -----------------------------------------------

def _fixtures_db(path: Path) -> Path:
    con = storage.connect(path)
    for fixture in sorted(FIXTURES.glob("*.json")):
        pipeline.ingest(con, json.loads(fixture.read_text(encoding="utf-8")))
    domains.resolve(con, load_companies(DEFAULT_CSV), {}, None)
    con.close()
    return path


def test_company_domain_sur_les_quatre_routes(tmp_path, monkeypatch):
    monkeypatch.delenv("JOB_REC_TOKEN", raising=False)
    with TestClient(api.create_app(_fixtures_db(tmp_path / "jobs.duckdb"))) as c:
        listed = c.get("/jobs", params={"per_page": 50}).json()["jobs"]
        assert listed and all(j["company_domain"] for j in listed)  # chaque fixture en a un
        first = listed[0]
        assert c.get(f"/jobs/{first['id']}").json()["company_domain"] == first["company_domain"]
        similar = c.get(f"/jobs/{first['id']}/similar").json()
        assert similar and all("company_domain" in j for j in similar)
        recos = c.post("/recommend", json={"cv_text": "Python data cloud", "k": 5}).json()
        assert recos and all(r["company_domain"] for r in recos)
        by_company = {j["company"]: j["company_domain"] for j in listed}
        assert by_company.get("Vitol", "vitol.com") == "vitol.com"


def test_base_sans_table_des_domaines(tmp_path, monkeypatch):
    """Une base d'avant cette version (aucune résolution) : company_domain vaut null."""
    monkeypatch.delenv("JOB_REC_TOKEN", raising=False)
    con = _db(tmp_path, ("Acme",))
    con.execute("DROP TABLE company_domains")
    con.close()
    with TestClient(api.create_app(tmp_path / "jobs.duckdb")) as c:
        job = c.get("/jobs").json()["jobs"][0]
        assert job["company_domain"] is None
        reco = c.post("/recommend", json={"cv_text": "Python"}).json()[0]
        assert reco["company_domain"] is None
