"""careers.un.org : faux portail (liste paginée), puis vraie fixture."""

import json
from datetime import date
from pathlib import Path

import httpx

from job_rec_ai.connectors import REGISTRY, uncareers
from job_rec_ai.geo import is_target
from job_rec_ai.http import PoliteClient

FIXTURE = Path(__file__).parent / "fixtures" / "uncareers.json"
SITE = "https://careers.un.example"


def _opening(job_id, *stations):
    return {"jobId": job_id, "jobTitle": f"Officer {job_id}",
            "postingTitle": f"Officer {job_id}, 15",
            "dutyStation": [{"description": s} for s in stations],
            "jobDescription": "<div><b>Org. Setting</b> OHCHR</div>",
            "startDate": "2026-11-03T05:00:00.000Z", "recrttype": {"name": "Intern"}}


OPENINGS = [_opening(1, "GENEVA"), _opening(2, "NEW YORK"), _opening(3, "NAIROBI", "GENEVA")]


def test_uncareers_fetch_et_parse(sleeps, monkeypatch):
    monkeypatch.setattr(uncareers, "PAGE_SIZE", 2)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        page = json.loads(request.content)["pagination"]["page"]
        return httpx.Response(200, json={"data": {"list": OPENINGS[page * 2:page * 2 + 2],
                                                  "count": len(OPENINGS)}})

    connector = REGISTRY["uncareers"]
    with PoliteClient(transport=httpx.MockTransport(handler), sleep=sleeps.append) as client:
        payload = connector.fetch(SITE, "ONU", client, keep=is_target)
    assert [p["jobId"] for p in payload["postings"]] == [1, 3]  # New York écarté
    first, multi = connector.parse(payload)
    assert first.title == "Officer 1"  # jobTitle, sans le suffixe interne de postingTitle
    assert str(first.url) == f"{SITE}/jobSearchDescription/1?language=en"
    assert (first.description, first.posted_at, first.employment_type) == (
        "Org. Setting OHCHR", date(2026, 11, 3), "Intern")
    assert multi.location == "NAIROBI / GENEVA"


def test_uncareers_parse_vraie_fixture():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    jobs = REGISTRY["uncareers"].parse(payload)
    assert len(jobs) == len(payload["postings"])
    assert all(len(j.description) > 500 and is_target(j.location) for j in jobs)
