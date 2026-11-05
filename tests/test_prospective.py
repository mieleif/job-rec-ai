"""Prospective : API publique paginée, lieu structuré (ville + NPA), parse sur la vraie fixture."""

import json
from pathlib import Path

import httpx
import pytest

from job_rec_ai.connectors import REGISTRY, prospective
from job_rec_ai.geo import is_target
from job_rec_ai.http import PoliteClient

FIXTURE = Path(__file__).parent / "fixtures" / "prospective.json"
BOARD = "https://ohws.prospective.example/public/v1/medium/42"


def _job(jid, title, city, zip_code, country="Schweiz"):
    return {"id": jid, "viewkey": f"vk-{jid}", "title": title, "szas": {
        "sza_title": title, "sza_location.city": city, "sza_location.zip": zip_code,
        "sza_location.country": country, "sza_introduction": "<p>Bienvenue</p>",
        "sza_tasks": "<ul><li>Conseiller</li></ul>", "sza_requirements": "<p>CFC</p>",
        "sza_pensum": "Vollzeit", "sza_field_of_activity": "Vente", "sza_role": "Cadre"}}


@pytest.fixture
def pro_client(sleeps, monkeypatch):
    monkeypatch.setattr(prospective, "PAGE_SIZE", 2)
    jobs = [_job(1, "Conseiller", "Genève", "1204"), _job(2, "Analyst", "Zürich", "8001"),
            # commune inconnue de geo : le NPA la situe (Vaud)
            _job(3, "Gestionnaire", "Bioley-Magnoux", "1407")]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        assert request.url.path == "/public/v1/medium/42/jobs"
        offset, limit = int(request.url.params["offset"]), int(request.url.params["limit"])
        return httpx.Response(200, json={"total": 3, "jobs": jobs[offset:offset + limit]})

    with PoliteClient(transport=httpx.MockTransport(handler), sleep=sleeps.append) as client:
        yield client


def test_prospective_fetch_pagine_filtre_et_parse(pro_client):
    connector = REGISTRY["prospective"]
    payload = connector.fetch(BOARD, "Helvetia", pro_client, keep=is_target)
    first, second = connector.parse(payload)  # 2 pages ; Zurich écarté
    assert (first.location, second.location) == ("Genève, CH-1204", "Bioley-Magnoux, CH-1407")
    assert str(first.url) == "https://ohws.prospective.ch/public/v1/jobs/vk-1"
    assert first.description == "Bienvenue Conseiller CFC" and first.source_id == "1"
    assert (first.category, first.level, first.employment_type) == ("Vente", "Cadre", "Vollzeit")


def test_npa_seulement_en_suisse():
    # sans pays suisse, un code postal à 4 chiffres ne prouve rien
    assert prospective.location_of({"sza_location.city": "Wien", "sza_location.zip": "1010",
                                    "sza_location.country": "Österreich"}) == "Wien, 1010"


def test_prospective_parse_vraie_fixture():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    jobs = REGISTRY["prospective"].parse(payload)
    assert len(jobs) == len(payload["postings"])  # aucune offre réelle rejetée
    assert all(j.company == "Helvetia Baloise" and is_target(j.location)
               and j.description and "<" not in j.description for j in jobs)
