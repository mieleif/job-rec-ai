"""Phenom : faux site (recherche paginée + annonces en phApp.ddo), puis vraie fixture."""

import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from job_rec_ai.connectors import REGISTRY, phenom
from job_rec_ai.geo import is_target
from job_rec_ai.http import PoliteClient

FIXTURE = Path(__file__).parent / "fixtures" / "phenom.json"
SITE = "https://careers.acme.example/global/en"


def _page(data):
    return f"<html><script>phApp.ddo = {json.dumps(data)}; phApp.sessionParams = {{}};</script>"


def _item(job_id, place):
    # Dans la liste, les lieux sont du texte
    return {"jobId": job_id, "title": f"Poste {job_id}", "multi_location": [place]}


ITEMS = [_item("1", "Vernier, Switzerland"), _item("2", "Kemptthal, Switzerland"),
         _item("3", "Lausanne, Switzerland")]
JOB = {"jobId": "1", "title": "Opérateur de production", "type": "Regular",
       "description": "<p>Rejoignez <b>Vernier</b></p>",
       "postedDate": "2026-06-24T00:00:00.000+0000",
       # Dans l'annonce, ce sont des objets ; et des champs lourds qu'on n'archive pas
       "multi_location": [{"location": "Vernier, Switzerland", "latitude": "46.2"}],
       "emb_complete_desc": [0.1] * 50}


@pytest.fixture
def phenom_client(sleeps, monkeypatch):
    monkeypatch.setattr(phenom, "PAGE_SIZE", 2)

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: */apply\n")
        if path.endswith("/search-results"):
            assert request.url.params["qcountry"] == "Switzerland"
            start = int(request.url.params["from"])
            return httpx.Response(200, text=_page({"eagerLoadRefineSearch": {
                "totalHits": len(ITEMS), "data": {"jobs": ITEMS[start:start + 2]}}}))
        if path.endswith("/job/1/"):
            return httpx.Response(200, text=_page({"jobDetail": {"data": {"job": JOB}}}))
        return httpx.Response(404)  # 3 : retirée

    with PoliteClient(transport=httpx.MockTransport(handler), sleep=sleeps.append) as client:
        yield client


def test_phenom_fetch_et_parse(phenom_client):
    connector = REGISTRY["phenom"]
    payload = connector.fetch(SITE, "Acme", phenom_client, keep=is_target)
    assert [p["jobId"] for p in payload["postings"]] == ["1"]  # Kemptthal (ZH) écarté, 3 en 404
    assert "emb_complete_desc" not in payload["postings"][0]
    (job,) = connector.parse(payload)
    assert (job.title, job.location, job.description) == (
        "Opérateur de production", "Vernier, Switzerland", "Rejoignez Vernier")
    assert job.posted_at == date(2026, 6, 24) and str(job.url) == f"{SITE}/job/1/"


def test_phenom_page_sans_donnees(phenom_client, monkeypatch):
    def broken(*args, **kwargs):
        return "<html>maintenance</html>"

    monkeypatch.setattr(phenom_client, "get_html", broken)
    with pytest.raises(ValueError):  # une collecte vide expirerait toutes les offres
        REGISTRY["phenom"].fetch(SITE, "Acme", phenom_client, keep=is_target)


def test_phenom_parse_vraie_fixture():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    jobs = REGISTRY["phenom"].parse(payload)
    assert len(jobs) == len(payload["postings"])
    assert all(j.description and "<" not in j.description and is_target(j.location)
               for j in jobs)
