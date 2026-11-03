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
}
SITEMAP = "<urlset>" + "".join(
    f"<url><loc>{SITE}{path}</loc><lastmod>2026-10-31</lastmod></url>" for path in PAGES
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
        return httpx.Response(200, text=PAGES[path]) if path in PAGES else httpx.Response(404)

    with PoliteClient(transport=httpx.MockTransport(handler), sleep=sleeps.append) as client:
        yield client


def test_successfactors_fetch_et_parse(sf_client):
    connector = REGISTRY["successfactors"]
    payload = connector.fetch(SITE, "Acme", sf_client, keep=is_target)
    assert [p["url"].rsplit("/", 2)[1] for p in payload["postings"]] == ["101", "102"]  # sans Paris
    assert "gabarit" not in payload["postings"][0]["html"]  # seules les microdonnées archivées

    classic, recent = connector.parse(payload)
    assert (classic.title, classic.location, classic.posted_at) == (
        "Ingénieur de données", "Meyrin, CH", date(2026, 11, 3))
    assert classic.source_id == "101" and "pipelines" in classic.description
    # Récente : lieu tiré de l'URL, date du sitemap, description recollée bloc par bloc
    assert (recent.location, recent.posted_at) == ("Lausanne", date(2026, 10, 31))
    assert recent.description == "Et si votre carrière continuait ici ? Vos missions : le budget."


def test_gros_sitemap_prefiltre_sur_l_url(sf_client, requested, monkeypatch):
    monkeypatch.setattr(successfactors, "FULL_SCAN_MAX", 2)  # 3 annonces : « gros » sitemap
    REGISTRY["successfactors"].fetch(SITE, "Acme", sf_client, keep=is_target)
    assert "/job/Paris-Analyste/103/" not in requested  # écartée sans être téléchargée


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
