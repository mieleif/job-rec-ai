"""Workable : fetch sur un faux widget (filtre de lieu, multi-sites), parse sur la vraie fixture."""

import json
from datetime import date
from pathlib import Path

import httpx

from job_rec_ai.connectors import REGISTRY
from job_rec_ai.geo import is_target
from job_rec_ai.http import PoliteClient

FIXTURE = Path(__file__).parent / "fixtures" / "workable.json"


def _job(code, title, city, locations=None):
    job = {"title": title, "shortcode": code, "url": f"https://apply.workable.com/j/{code}",
           "city": city, "state": "", "country": "Switzerland", "published_on": "2026-10-02",
           "employment_type": "Full-time", "department": "R&D",
           "description": "<p>Chimie &amp; <b>biologie</b></p>"}
    if locations:
        job["locations"] = locations
    return job


def _handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/robots.txt":
        return httpx.Response(404)
    assert request.url.path == "/api/v1/widget/accounts/acme"
    assert request.url.params["details"] == "true"  # sans ça, pas de description
    return httpx.Response(200, json={"name": "Acme", "jobs": [
        _job("A1", "Laborantin·e", "Martigny"),
        _job("B2", "Statisticien·ne", "Zürich"),
        # multi-sites : gardée si l'un des lieux est romand
        _job("C3", "Auditeur·rice", "Basel", locations=[
            {"city": "Basel", "country": "Switzerland"},
            {"city": "Lausanne", "country": "Switzerland"}]),
    ]})


def test_workable_fetch_filtre_et_parse(sleeps):
    connector = REGISTRY["workable"]
    with PoliteClient(transport=httpx.MockTransport(_handler), sleep=sleeps.append) as client:
        payload = connector.fetch("acme", "Acme", client, keep=is_target)
    first, second = connector.parse(payload)
    assert (first.title, second.title) == ("Laborantin·e", "Auditeur·rice")  # Zürich écarté
    assert first.location == "Martigny, Switzerland"
    assert second.location == "Basel, Switzerland / Lausanne, Switzerland"
    assert first.description == "Chimie & biologie" and first.posted_at == date(2026, 10, 2)
    assert (first.source_id, first.employment_type, first.category) == ("A1", "Full-time", "R&D")


def test_workable_parse_vraie_fixture():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    jobs = REGISTRY["workable"].parse(payload)
    assert len(jobs) == len(payload["postings"])  # aucune offre réelle rejetée
    assert all(j.company == "Debiopharm" and j.description and "<" not in j.description
               for j in jobs)
