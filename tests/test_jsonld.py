"""JSON-LD : faux site maison (liste paginée + annonces balisées), extraction du JobPosting."""

import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from job_rec_ai.connectors import REGISTRY
from job_rec_ai.connectors.schema_org import json_ld_job_posting
from job_rec_ai.geo import is_target
from job_rec_ai.http import PoliteClient

FIXTURE = Path(__file__).parent / "fixtures" / "jsonld.json"
SITE = "https://www.etat.example"
BOARD = f"{SITE}/emplois/offres"


def ad(title, locality=None, extra=""):
    job = {"@context": "https://schema.org/", "@type": "JobPosting", "title": title,
           "description": "<p>Vous l&#039;aimerez : <b>Python</b>.</p>",
           "datePosted": "2026-10-20", "employmentType": ["FULL_TIME", "PART_TIME"],
           "identifier": {"@type": "PropertyValue", "value": "REF-1"}}
    if locality:
        job["jobLocation"] = {"@type": "Place", "address": {"addressLocality": locality,
                                                           "addressCountry": "CH"}}
    return (f'<html><head><script type="application/ld+json">{json.dumps(job)}</script>'
            f"</head><body>{extra}</body></html>")


PAGES = {
    "/emplois/offres": '<a href="/emplois/offres/1">Analyste</a><a href="/emplois/offres/2#x">'
                       'Juriste</a><a href="/autre/page">Hors sujet</a>'
                       '<a rel="next" href="/emplois/offres?page=2">Suivant</a>',
    "/emplois/offres?page=2": '<a href="/emplois/offres/3">Zurich</a>'
                              '<a href="/emplois/offres/4">Pas une annonce</a>'
                              '<a href="/emplois/offres/5">Retirée</a>',  # 404 : ignorée
    "/emplois/offres/1": ad("Analyste de données", "Genève"),
    "/emplois/offres/2": ad("Juriste"),  # sans lieu : gardée
    "/emplois/offres/3": ad("Huissier", "Place du  Bourg-de-Four 1​&amp;#160;"),
    "/emplois/offres/4": "<html><body>Page d'information</body></html>",
}


@pytest.fixture
def site_client(sleeps):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        key = request.url.path + (f"?{request.url.query.decode()}" if request.url.query else "")
        return httpx.Response(200, text=PAGES[key]) if key in PAGES else httpx.Response(404)

    with PoliteClient(transport=httpx.MockTransport(handler), sleep=sleeps.append) as client:
        yield client


def test_jsonld_fetch_et_parse(site_client):
    connector = REGISTRY["jsonld"]
    payload = connector.fetch(BOARD, "État", site_client, keep=is_target)
    # page 2 suivie via rel="next" ; la page sans JSON-LD ignorée ; pas de filtre de lieu
    assert [p["url"].rsplit("/", 1)[1] for p in payload["postings"]] == ["1", "2", "3"]
    first, second, third = connector.parse(payload)
    assert (first.title, first.location, first.posted_at) == (
        "Analyste de données", "Genève, CH", date(2026, 10, 20))
    assert first.description == "Vous l'aimerez : Python."  # entités et balises nettoyées
    assert first.employment_type == "FULL_TIME, PART_TIME" and first.source_id == "REF-1"
    assert second.location == ""  # pas de lieu publié : le canton viendra de l'employeur
    assert third.location == "Place du Bourg-de-Four 1, CH"  # entités et U+200B nettoyés


@pytest.mark.parametrize("html", [
    '<script type="application/ld+json">[{"@type": "WebSite"}, {"@type": "JobPosting", '
    '"title": "A"}]</script>',
    '<script type="application/ld+json">{"@graph": [{"@type": "BreadcrumbList"}, '
    '{"@type": "JobPosting", "title": "A"}]}</script>',
    # retour à la ligne brut dans une chaîne : JSON invalide au sens strict, toléré
    '<script type="application/ld+json">{"@type": "JobPosting", "title": "A\nB"}</script>',
    # guillemets simples, @type en liste
    "<script type='application/ld+json'>{\"@type\": [\"JobPosting\"], \"title\": \"A\"}</script>",
])
def test_json_ld_formes(html):
    assert json_ld_job_posting(html)["title"].startswith("A")


def test_json_ld_absent_ou_casse():
    assert json_ld_job_posting("<script type='text/javascript'>{}</script>") is None
    assert json_ld_job_posting('<script type="application/ld+json">{oops</script>') is None
    assert json_ld_job_posting('<script type="application/ld+json">"x"</script>') is None


def test_adresse_en_liste():
    from job_rec_ai.connectors.jsonld import location_text
    job = {"jobLocation": {"address": [{"addressLocality": "Genève"}, "Rue du Stand 46"]}}
    assert location_text(job) == "Genève / Rue du Stand 46"


def test_vraie_fixture_texte_propre():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    jobs = REGISTRY["jsonld"].parse(payload)
    assert len(jobs) == len(payload["postings"])
    for job in jobs:
        for text in (job.title, job.description, job.location):
            assert "&#" not in text and "&quot;" not in text and "\u200b" not in text
