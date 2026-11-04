"""Taleo : faux serveur (page de recherche, API de liste, annonces), puis vraie fixture (OMPI)."""

import json
from pathlib import Path

import httpx
import pytest

from job_rec_ai.connectors import REGISTRY
from job_rec_ai.connectors.taleo import description_fields, locations_of
from job_rec_ai.geo import is_target
from job_rec_ai.http import PoliteClient

FIXTURE = Path(__file__).parent / "fixtures" / "taleo.json"
HOST = "https://acme.taleo.net"
BOARD = f"{HOST}/careersection/ex/jobsearch.ftl?lang=en"
SEARCH_PAGE = "<script>var settings = { lang: 'en', portalNo: '1234567', other: 1 };</script>"


def _row(no, title, place):
    # Colonnes propres à l'employeur : ici le titre en 0, le grade en 1, les lieux en 2
    return {"jobId": no, "contestNo": f"C-{no}", "linkedColumn": 0, "locationsColumns": [2],
            "column": [title, "P3", json.dumps([place])]}


ROWS = [_row("1", "Data Officer", "Switzerland-Geneva"), _row("2", "Driver", "Ukraine-Kyiv"),
        _row("3", "Interpreter", "Switzerland-Geneva")]


def _detail(text):
    encoded = text.replace("<", "%3C").replace(">", "%3E")
    return ("<html><script>api.fillList('requisitionDescriptionInterface', 'descRequisition', "
            f"['406785','true','L\\'Organisation','!*!{encoded}']);</script></html>")


@pytest.fixture
def taleo_client(sleeps):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/robots.txt":
            return httpx.Response(404)
        if path == "/careersection/ex/jobsearch.ftl":
            return httpx.Response(200, text=SEARCH_PAGE)
        if path == "/careersection/rest/jobboard/searchjobs":
            assert request.url.params["portal"] == "1234567"
            assert request.headers["tz"]  # sans ces en-têtes, le vrai serveur répond 500
            page = json.loads(request.content)["pageNo"]
            rows = ROWS[(page - 1) * 25:page * 25]
            return httpx.Response(200, json={"requisitionList": rows,
                                             "pagingData": {"totalCount": len(ROWS)}})
        job = request.url.params["job"]
        if job == "C-1":
            return httpx.Response(200, text=_detail("<p>Analyse de <b>données</b></p>"))
        return httpx.Response(404)  # C-3 : retirée entre la liste et l'annonce

    with PoliteClient(transport=httpx.MockTransport(handler), sleep=sleeps.append) as client:
        yield client


def test_taleo_fetch_et_parse(taleo_client):
    connector = REGISTRY["taleo"]
    payload = connector.fetch(BOARD, "Acme", taleo_client, keep=is_target)
    assert [p["contestNo"] for p in payload["postings"]] == ["C-1"]  # Kyiv écarté, C-3 en 404
    (job,) = connector.parse(payload)
    assert (job.title, job.location, job.source_id) == ("Data Officer", "Switzerland-Geneva", "C-1")
    assert job.description == "Analyse de données"  # HTML décodé, marqueur !*! retiré
    assert str(job.url) == f"{HOST}/careersection/ex/jobdetail.ftl?job=C-1&lang=en"


def test_champs_de_l_annonce():
    assert description_fields(_detail("x"))[2] == "L'Organisation"  # apostrophe échappée
    assert description_fields("<html>pas d'annonce</html>") is None
    assert locations_of({"locationsColumns": [1], "column": ["T", "Genève"]}) == ["Genève"]


def test_taleo_parse_vraie_fixture():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    jobs = REGISTRY["taleo"].parse(payload)
    assert len(jobs) == len(payload["postings"])
    assert all(len(j.description) > 500 and "%3C" not in j.description and "!*!" not in
               j.description and is_target(j.location) for j in jobs)
