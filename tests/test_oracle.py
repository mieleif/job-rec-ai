"""Oracle Recruiting Cloud : faux serveur (liste paginée + détails), puis vraie fixture (UBP)."""

import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from job_rec_ai.connectors import REGISTRY, oracle
from job_rec_ai.geo import is_target
from job_rec_ai.http import PoliteClient

FIXTURE = Path(__file__).parent / "fixtures" / "oracle.json"
HOST = "https://acme.fa.ocs.oraclecloud.eu"
BOARD = f"{HOST}/hcmUI/CandidateExperience/en/sites/CX_1/requisitions"

LIST = [
    {"Id": "1", "Title": "Analyste crédit", "PrimaryLocation": "Geneva, Switzerland",
     "PrimaryLocationCountry": "CH", "secondaryLocations": []},
    {"Id": "2", "Title": "Banquier privé", "PrimaryLocation": "Paris, France",
     "PrimaryLocationCountry": "FR", "secondaryLocations": [{"Name": "Lausanne, Switzerland"}]},
    {"Id": "3", "Title": "Juriste", "PrimaryLocation": "Paris, France",
     "PrimaryLocationCountry": "FR", "secondaryLocations": []},
    # Pays seul : le détail dit la ville
    {"Id": "4", "Title": "Stagiaire RH", "PrimaryLocation": "Switzerland",
     "PrimaryLocationCountry": "CH", "secondaryLocations": []},
]


def _detail(item, town=None):
    return {**item, "ExternalDescriptionStr": "<p>La <b>mission</b></p>",
            "ExternalQualificationsStr": "<ul><li>Python</li></ul>",
            "ExternalResponsibilitiesStr": None, "JobSchedule": "Full time",
            "ExternalPostedStartDate": "2026-11-02T13:31:38+00:00",
            "workLocation": [{"TownOrCity": town}]}


DETAILS = {"1": _detail(LIST[0], "Genève"), "2": _detail(LIST[1]),
           "4": _detail(LIST[3], "Zurich")}


@pytest.fixture
def requested():
    return []


@pytest.fixture
def oracle_client(sleeps, requested, monkeypatch):
    monkeypatch.setattr(oracle, "PAGE_SIZE", 2)  # 4 offres : deux pages

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        finder = request.url.params["finder"]
        requested.append(finder)
        if request.url.path.endswith("/recruitingCEJobRequisitions"):
            assert "siteNumber=CX_1" in finder and "location=Switzerland" in finder
            offset = int(finder.split("offset=")[1].split(",")[0])
            return httpx.Response(200, json={"items": [{
                "TotalJobsCount": len(LIST), "requisitionList": LIST[offset:offset + 2]}]})
        job_id = finder.split('Id="')[1].split('"')[0]
        return httpx.Response(200, json={"items": [DETAILS[job_id]]})

    with PoliteClient(transport=httpx.MockTransport(handler), sleep=sleeps.append) as client:
        yield client


def test_site_of():
    assert oracle.site_of(BOARD) == (HOST, "CX_1")
    with pytest.raises(ValueError):
        oracle.site_of("https://acme.example/careers")


def test_oracle_fetch_et_parse(oracle_client, requested):
    connector = REGISTRY["oracle"]
    payload = connector.fetch(BOARD, "Acme", oracle_client, keep=is_target)
    # 1 : Genève ; 2 : lieu secondaire à Lausanne ; 3 : Paris, détail jamais demandé ;
    # 4 : « Switzerland » seul, détail demandé, mais à Zurich
    assert [p["Id"] for p in payload["postings"]] == ["1", "2"]
    assert not any('Id="3"' in f for f in requested)
    first, second = connector.parse(payload)
    assert first.url.path == "/hcmUI/CandidateExperience/en/sites/CX_1/job/1"
    assert (first.location, second.location) == ("Geneva, Switzerland / Genève",
                                                 "Paris, France / Lausanne, Switzerland")
    assert first.description == "La mission Python"
    assert first.posted_at == date(2026, 11, 2) and first.employment_type == "Full time"


def test_oracle_parse_vraie_fixture():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    jobs = REGISTRY["oracle"].parse(payload)
    assert len(jobs) == len(payload["postings"])
    assert all(j.description and "<" not in j.description and is_target(j.location)
               for j in jobs)
