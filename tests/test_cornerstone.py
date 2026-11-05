"""Cornerstone : jeton lu dans la page publique, recherche paginée, dates selon la culture."""

import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from job_rec_ai.connectors import REGISTRY, cornerstone
from job_rec_ai.geo import is_target
from job_rec_ai.http import PoliteClient

FIXTURE = Path(__file__).parent / "fixtures" / "cornerstone.json"
BOARD = "https://acme.csod.com/ux/ats/careersite/4/home"
CONTEXT = {"corp": "acme", "cultureID": 2, "cultureName": "en-GB", "token": "JETON",
           "endpoints": {"cloud": "https://api.acme.example/", "api": "/"}}


def _req(rid, title, city, country="CH"):
    place = {"city": city, "country": country} if country else {"city": city, "state": "VS"}
    return {"requisitionId": rid, "displayJobTitle": title, "postingEffectiveDate": "04/11/2026",
            "locations": [place],
            "externalDescription": "<p>Logistique &amp; <b>douane</b></p>"}


@pytest.fixture
def csod_client(sleeps, monkeypatch):
    monkeypatch.setattr(cornerstone, "PAGE_SIZE", 2)
    pages = {1: [_req(1, "Analyste", "Geneva"), _req(2, "Planner", "Zug")],
             2: [_req(3, "Juriste", "Lausanne")]}
    seen_filters = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        if request.url.host == "acme.csod.com":
            assert request.url.params["c"] == "acme"
            return httpx.Response(200, text=f"<script>csod.context={json.dumps(CONTEXT)};</script>")
        assert request.headers["Authorization"] == "Bearer JETON"  # le jeton de la page
        body = json.loads(request.content)
        assert body["careerSiteId"] == 4
        seen_filters.append(body["countryCodes"])
        return httpx.Response(200, json={"data": {"totalCount": 3,
                                                  "requisitions": pages[body["pageNumber"]]}})

    with PoliteClient(transport=httpx.MockTransport(handler), sleep=sleeps.append) as client:
        client.seen_filters = seen_filters
        yield client


def test_cornerstone_fetch_pagine_filtre_et_parse(csod_client):
    connector = REGISTRY["cornerstone"]
    payload = connector.fetch(BOARD, "Acme", csod_client, keep=is_target)
    jobs = connector.parse(payload)
    assert [j.title for j in jobs] == ["Analyste", "Juriste"]  # 2 pages ; Zoug écarté
    first = jobs[0]
    assert str(first.url) == f"{BOARD}/requisition/1?c=acme"
    assert first.location == "Geneva, CH" and first.description == "Logistique & douane"
    assert first.posted_at == date(2026, 11, 4)  # en-GB : jour/mois
    assert csod_client.seen_filters == [[], []]  # petit board : lu en entier (2 pages), filtré ici


def test_grand_board_filtre_par_le_serveur(csod_client, monkeypatch):
    monkeypatch.setattr(cornerstone, "MAX_PAGES", 1)  # 3 offres > 2 × 1 : trop pour tout lire
    REGISTRY["cornerstone"].fetch(BOARD, "Acme", csod_client, keep=is_target)
    assert csod_client.seen_filters[1:] == [["ch"]]


def test_lieu_sans_pays():
    # Groupe Mutuel : ville et canton seulement
    assert cornerstone._places(_req(9, "Stagiaire", "Martigny", country=None)) == ["Martigny, VS"]


@pytest.mark.parametrize("value, culture, expected", [
    ("04/11/2026", "en-GB", date(2026, 11, 4)), ("11/04/2026", "en-US", date(2026, 11, 4)),
    ("-", "en-GB", None), (None, "en-GB", None),
])
def test_dates_selon_la_culture(value, culture, expected):
    assert cornerstone.posted_on(value, culture) == expected


def test_cornerstone_parse_vraie_fixture():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    jobs = REGISTRY["cornerstone"].parse(payload)
    assert len(jobs) == len(payload["postings"])  # aucune offre réelle rejetée
    assert all(j.company == "MSC" and j.posted_at and "<" not in j.description for j in jobs)
