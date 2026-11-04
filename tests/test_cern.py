"""CERN : faux site (liste + articles WordPress), puis vraie fixture."""

import json
from pathlib import Path

import httpx
import pytest

from job_rec_ai.connectors import REGISTRY
from job_rec_ai.geo import is_target
from job_rec_ai.http import PoliteClient

FIXTURE = Path(__file__).parent / "fixtures" / "cern.json"
BOARD = "https://careers.cern.example/jobs/"


def _article(title, place):
    return (f'<html><nav>menu</nav><main><article class="job_offer"><h1>{title}</h1>'
            '<div class="job-offer__header-infos"><div class="meta">'
            f'<span class="location"><img alt="flag"> {place} </span>'
            '<span class="ref">EN-2026-250</span></div></div>'
            '<div class="entry-content"><h3>What you\'ll do</h3><p>Design <b>magnets</b>.</p>'
            "</div></article></main></html>")


PAGES = {
    "/jobs/": '<a href="/jobs/engineer/">Engineer</a><a href="/jobs/technician/">Technician</a>'
              '<a href="/jobs/feed/">RSS</a><a href="/about/">À propos</a>',
    "/jobs/engineer/": _article("Mechanical Engineer", "Geneva, Switzerland"),
    "/jobs/technician/": _article("Technician", "Prévessin, France"),
    "/jobs/feed/": "<rss></rss>",  # pas un article : ignoré
}


def _client(sleeps, pages):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /wp-admin/\n")
        page = pages.get(request.url.path)
        return httpx.Response(200, text=page) if page else httpx.Response(404)

    return PoliteClient(transport=httpx.MockTransport(handler), sleep=sleeps.append)


def test_cern_fetch_et_parse(sleeps):
    connector = REGISTRY["cern"]
    with _client(sleeps, PAGES) as client:
        payload = connector.fetch(BOARD, "CERN", client, keep=is_target)
    (job,) = connector.parse(payload)  # Prévessin (France) écarté
    assert (job.title, job.location, job.source_id) == (
        "Mechanical Engineer", "Geneva, Switzerland", "EN-2026-250")
    assert job.description == "What you'll do Design magnets."
    assert "menu" not in payload["postings"][0]["html"]  # seul l'article est archivé


def test_cern_theme_change_erreur_explicite(sleeps):
    pages = {**PAGES, "/jobs/engineer/": "<html>nouveau thème</html>",
             "/jobs/technician/": "<html>nouveau thème</html>"}
    with _client(sleeps, pages) as client, pytest.raises(ValueError):
        REGISTRY["cern"].fetch(BOARD, "CERN", client, keep=is_target)


def test_cern_parse_vraie_fixture():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    jobs = REGISTRY["cern"].parse(payload)
    assert len(jobs) == len(payload["postings"])
    assert all(len(j.description) > 500 and j.source_id and is_target(j.location) for j in jobs)
