"""Greenhouse : fetch sur un faux serveur (filtre de lieu), parse sur la vraie fixture."""

import json
from datetime import date
from pathlib import Path

import httpx

from job_rec_ai.connectors import REGISTRY
from job_rec_ai.geo import is_target
from job_rec_ai.http import PoliteClient

FIXTURE = Path(__file__).parent / "fixtures" / "greenhouse.json"


def _job(jid, title, location):
    return {"id": jid, "title": title, "location": {"name": location},
            "absolute_url": f"https://job-boards.greenhouse.io/acme/jobs/{jid}",
            "content": "&lt;p&gt;Python &amp;amp; SQL&lt;/p&gt;", "language": "fr",
            "first_published": "2026-10-01T09:00:00-04:00",
            "metadata": [{"name": "Employment Type", "value": "Full-time"}]}


def _handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/robots.txt":
        return httpx.Response(200, text="User-agent: *\nDisallow: /embed/\n")
    assert request.url.params["content"] == "true"  # sans ça, pas de description
    return httpx.Response(200, json={"jobs": [
        _job(1, "Data Engineer", "Geneva, Switzerland, Paris, France"),
        _job(2, "Account Manager", "Paris"),
    ]})


def test_greenhouse_fetch_filtre_et_parse(sleeps):
    connector = REGISTRY["greenhouse"]
    with PoliteClient(transport=httpx.MockTransport(_handler), sleep=sleeps.append) as client:
        payload = connector.fetch("acme", "Acme", client, keep=is_target)
    jobs = connector.parse(payload)
    assert [j.title for j in jobs] == ["Data Engineer"]  # Paris écarté
    job = jobs[0]
    assert job.company == "Acme" and job.source == "greenhouse" and job.source_id == "1"
    assert job.description == "Python & SQL"  # HTML doublement échappé, nettoyé
    assert job.language == "fr" and job.employment_type == "Full-time"
    assert job.posted_at == date(2026, 10, 1)


def test_greenhouse_parse_vraie_fixture():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    jobs = REGISTRY["greenhouse"].parse(payload)
    assert len(jobs) == len(payload["postings"])  # aucune offre réelle rejetée
    assert all(j.company == "Proton" and "<" not in j.description for j in jobs)
