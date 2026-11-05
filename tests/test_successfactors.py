"""SuccessFactors : faux site carrière (les deux générations de pages), puis vraie fixture."""

import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from job_rec_ai.connectors import REGISTRY, successfactors
from job_rec_ai.connectors.successfactors import location_from_url
from job_rec_ai.geo import is_target
from job_rec_ai.http import PoliteClient

SITE = "https://jobs.acme.example"
FIXTURE = Path(__file__).parent / "fixtures" / "successfactors.json"

# Ancienne génération : lieu et date en microdonnées
CLASSIC = """<html><head><script>track()</script></head><body><nav>gabarit</nav>
<span itemprop="jobLocation"><span itemprop="address">
<meta itemprop="streetAddress" content="Meyrin, CH"></span></span>
<meta itemprop="datePosted" content="Tue Nov 03 02:00:00 UTC 2026">
<span itemprop="title">Ingénieur de données</span>
<span itemprop="description"><p>Vous développerez nos <b>pipelines</b>.</p></span>
</body></html>"""
# Génération récente : titre et description (en plusieurs blocs) seulement
RECENT = """<html><body><nav>gabarit</nav>
<span itemprop="title">Contrôleur de gestion</span>
<span itemprop="description"><p>Et si votre carrière continuait ici ?</p></span>
<div>Bloc sans microdonnées</div>
<span itemprop="description"><p>Vos missions : le budget.</p></span>
</body></html>"""
ABROAD = CLASSIC.replace("Meyrin, CH", "Paris, FR").replace("Ingénieur de données", "Analyste")

PAGES = {
    "/job/Meyrin-Ingenieur-de-donnees/101/": CLASSIC,
    "/job/Lausanne-Controleur-de-gestion/102/": RECENT,
    "/job/Paris-Analyste/103/": ABROAD,
    # Siège à Vevey, titre qui nomme un pays : le pré-filtre ne doit pas l'écarter
    "/job/Vevey-Country-Manager-France/105/": CLASSIC.replace("Meyrin, CH", "Vevey, CH"),
}
# Encore dans le sitemap mais retirée : 404
GONE = "/job/Lausanne-Poste-pourvu/104/"
SITEMAP = "<urlset>" + "".join(
    f"<url><loc>{SITE}{path}</loc><lastmod>2026-10-31</lastmod></url>" for path in [*PAGES, GONE]
) + "</urlset>"


@pytest.fixture
def requested():
    return []


@pytest.fixture
def sf_client(sleeps, requested):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        requested.append(path)
        if path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /services/\n")
        if path == "/sitemap.xml":
            return httpx.Response(200, text=SITEMAP)
        if path not in PAGES:
            return httpx.Response(404)
        page = PAGES[path]
        return httpx.Response(page) if isinstance(page, int) else httpx.Response(200, text=page)

    with PoliteClient(transport=httpx.MockTransport(handler), sleep=sleeps.append) as client:
        yield client


def test_successfactors_fetch_et_parse(sf_client):
    connector = REGISTRY["successfactors"]
    payload = connector.fetch(SITE, "Acme", sf_client, keep=is_target)
    # sans Paris (hors cible) ni l'annonce retirée (404), qui ne fait pas échouer les autres
    assert [p["url"].rsplit("/", 2)[1] for p in payload["postings"]] == ["101", "102", "105"]
    assert "gabarit" not in payload["postings"][0]["html"]  # seules les microdonnées archivées

    classic, recent, _ = connector.parse(payload)
    assert (classic.title, classic.location, classic.posted_at) == (
        "Ingénieur de données", "Meyrin, CH", date(2026, 11, 3))
    assert classic.source_id == "101" and "pipelines" in classic.description
    # Récente : lieu tiré de l'URL, date du sitemap, description recollée bloc par bloc
    assert (recent.location, recent.posted_at) == ("Lausanne", date(2026, 10, 31))
    assert recent.description == "Et si votre carrière continuait ici ? Vos missions : le budget."


def test_gros_sitemap_prefiltre_sur_l_url(sf_client, requested, monkeypatch):
    monkeypatch.setattr(successfactors, "FULL_SCAN_MAX", 2)  # 5 annonces : « gros » sitemap
    payload = REGISTRY["successfactors"].fetch(SITE, "Acme", sf_client, keep=is_target)
    assert "/job/Paris-Analyste/103/" not in requested  # écartée sans être téléchargée
    assert any(p["url"].endswith("/105/") for p in payload["postings"])  # Vevey…France gardée


def test_site_en_panne_fait_echouer_l_employeur(sf_client, monkeypatch):
    monkeypatch.setitem(PAGES, "/job/Meyrin-Ingenieur-de-donnees/101/", 503)  # 503 persistant
    with pytest.raises(httpx.HTTPStatusError):  # remonte : pas d'expiration massive sur panne
        REGISTRY["successfactors"].fetch(SITE, "Acme", sf_client, keep=is_target)


@pytest.mark.parametrize(("value", "expected"), [
    ("Tue Nov 03 02:00:00 UTC 2026", date(2026, 11, 3)),
    ("Tue Nov 03 02:00:00 CET 2026", date(2026, 11, 3)),
    ("Sun Mar 29 03:00:00 CEST 2026", date(2026, 3, 29)),
    ("2026-10-31", date(2026, 10, 31)),
    (None, None),
])
def test_posted_on(value, expected):
    assert successfactors.posted_on(value) == expected


@pytest.mark.parametrize(("path", "title", "location"), [
    ("Lausanne-Responsable-Private-Banking-&-Advisory/1", "Responsable Private Banking & Advisory",
     "Lausanne"),
    # l'URL tronque la fin du titre : « Genè » pour « Genève »
    ("Le-Grand-Saconnex-Stagiaire-graphiste-Gen%C3%A8/137", "Stagiaire graphiste Genève",
     "Le Grand Saconnex"),
    ("Geneva-%28GVA%29-AI-Learning-Associate-33886/1", "AI Learning Associate", "Geneva GVA"),
    ("CDD-Charg%C3%A9-e-conduite/1", "CDD Chargé·e conduite", ""),  # pas de lieu dans l'URL
])
def test_location_from_url(path, title, location):
    assert location_from_url(f"{SITE}/job/{path}/", title) == location


def test_successfactors_parse_vraie_fixture():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    jobs = REGISTRY["successfactors"].parse(payload)
    assert len(jobs) == len(payload["postings"])  # aucune offre réelle rejetée
    assert all(is_target(j.location) and len(j.description) > 1000 for j in jobs)


def test_titre_hors_microdonnees(sleeps):
    """L'UIT n'a pas d'itemprop="title" : le titre vient de og:title, gardé à part."""
    page = ('<html><head><meta property="og:title" content="Roster - Interprète"></head><body>'
            '<span itemprop="description"><p>Interprétation</p></span></body></html>')

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/sitemap.xml":
            return httpx.Response(200, text=f"<url><loc>{SITE}/job/Geneva-Roster-Interprete/7/"
                                            "</loc></url>")
        return httpx.Response(200, text=page) if "/job/" in request.url.path else (
            httpx.Response(404))

    connector = REGISTRY["successfactors"]
    with PoliteClient(transport=httpx.MockTransport(handler), sleep=sleeps.append) as client:
        payload = connector.fetch(SITE, "UIT", client, keep=is_target)
    (job,) = connector.parse(payload)
    assert (job.title, job.location) == ("Roster - Interprète", "Geneva")


def test_lieu_commune_et_canton_en_microdonnees(sleeps):
    """Coop : la commune (inconnue de geo) et le canton à part ; le titre ne se retrouve
    pas dans l'URL (« Collaboratrice/Collaborateur » y devient un seul mot)."""
    page = ('<span itemprop="addressLocality">Aclens</span>'
            '<span itemprop="addressRegion">Vaud</span>'
            '<span itemprop="title">Collaboratrice/Collaborateur Vente</span>'
            '<span itemprop="description"><p>Vente</p></span>')

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/sitemap.xml":
            return httpx.Response(200, text=f"<url><loc>{SITE}/job/Aclens-CollaboratriceCollab"
                                            "orateur-Vente-Vaud/8/</loc></url>")
        return httpx.Response(200, text=page) if "/job/" in request.url.path else (
            httpx.Response(404))

    connector = REGISTRY["successfactors"]
    with PoliteClient(transport=httpx.MockTransport(handler), sleep=sleeps.append) as client:
        payload = connector.fetch(SITE, "Coop", client, keep=is_target)
    (job,) = connector.parse(payload)
    assert job.location == "Aclens, Vaud"


def test_canton_seul_en_microdonnees_l_url_d_abord():
    from job_rec_ai.connectors.schema_org import JobPostingPage
    from job_rec_ai.connectors.successfactors import location_of
    page = JobPostingPage('<span itemprop="addressRegion">CH</span>')
    assert location_of(page, f"{SITE}/job/Lausanne-Analyste/9/", "Analyste") == "Lausanne"


def test_champs_de_la_fiche_coop(sleeps):
    """Coop : pas de description, mais des champs « libellé : valeur » hors microdonnées,
    qui donnent la famille et le niveau quand le titre ne dit rien."""
    page = ('<span itemprop="addressLocality">Crissier</span>'
            '<span itemprop="addressRegion">Vaud</span>'
            '<span itemprop="title" data-careersite-propertyid="title">'
            'Collaboratrice / Collaborateur</span>'
            '<span itemprop="description" data-careersite-propertyid="description">'
            'Collaboratrice / Collaborateur</span>'
            '<div><span class="joblayouttoken-label">Poste: </span>'
            '<span data-careersite-propertyid="customfield3">Apprentie / Apprenti </span></div>'
            '<div><span class="joblayouttoken-label">Spécialisation professionnelle: </span>'
            '<span data-careersite-propertyid="shifttype">Vente Food</span></div>'
            '<div><span class="joblayouttoken-label">Taux d\'occupation: </span>'
            '<span data-careersite-propertyid="facility">80 - 100%</span></div>')

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/sitemap.xml":
            return httpx.Response(200, text=f"<url><loc>{SITE}/job/Crissier-Bouchere-Boucher-"
                                            "Vaud/9/</loc></url>")
        return httpx.Response(200, text=page)

    connector = REGISTRY["successfactors"]
    with PoliteClient(transport=httpx.MockTransport(handler), sleep=sleeps.append) as client:
        payload = connector.fetch(SITE, "Coop", client, keep=is_target)
    assert payload["postings"][0]["details"] == {
        "Poste": "Apprentie / Apprenti", "Spécialisation professionnelle": "Vente Food",
        "Taux d'occupation": "80 - 100%"}
    (job,) = connector.parse(payload)
    assert (job.category, job.level) == ("Vente Food", "Apprentie / Apprenti")

    from job_rec_ai.families import classify
    c = classify(job.title, job.description, job.category, job.level)
    assert (c.family, c.seniority) == ("Vente & Relation client", "Stage / Apprentissage")
