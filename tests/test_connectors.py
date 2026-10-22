from datetime import date

import pytest

from job_rec_ai.connectors import REGISTRY
from job_rec_ai.connectors.workday import api_base
from job_rec_ai.geo import is_target


@pytest.mark.parametrize("board", [
    "https://acme.wd3.myworkdayjobs.com/Acme_Careers",
    "https://acme.wd3.myworkdayjobs.com/en-US/Acme_Careers/",
])
def test_workday_api_base(board):
    assert api_base(board) == "https://acme.wd3.myworkdayjobs.com/wday/cxs/acme/Acme_Careers"


def test_workday_fetch_filtre_et_pagine(client):
    payload = REGISTRY["workday"].fetch("https://acme.wd3.myworkdayjobs.com/Acme_Careers",
                                        "Acme", client, keep=is_target)
    titles = [p["jobPostingInfo"]["title"] for p in payload["postings"]]
    # Basel écarté sans télécharger le détail ; « 2 Locations » gardé car Lausanne en fait partie
    assert titles == ["Data Engineer", "Comptable 80-100%"]


def test_workday_parse(client):
    connector = REGISTRY["workday"]
    payload = connector.fetch("https://acme.wd3.myworkdayjobs.com/Acme_Careers", "Acme",
                              client, keep=is_target)
    jobs = connector.parse(payload)
    first = jobs[0]
    assert first.company == "Acme"  # notre nom canonique, pas « Acme Holding SA »
    assert first.description == "We are looking for an engineer to join our team."
    assert first.posted_at == date(2026, 10, 1) and first.source_id == "R1"
    assert jobs[1].location == "Zürich / Lausanne"


def test_smartrecruiters_fetch_et_parse(client):
    connector = REGISTRY["smartrecruiters"]
    payload = connector.fetch("ACME", "Acme", client, keep=is_target)
    jobs = connector.parse(payload)
    assert [j.title for j in jobs] == ["Ingénieur de données"]
    job = jobs[0]
    assert job.location == "Meyrin, GE, ch"
    assert "pipelines" in job.description and "Python SQL" in job.description
    assert str(job.url) == "https://jobs.smartrecruiters.com/ACME/1-x"


def test_parse_ignore_les_offres_invalides():
    payload = {"ats": "smartrecruiters", "company": "Acme", "board": "ACME", "postings": [
        {"id": "9", "name": "   "},  # titre vide → rejetée, sans faire échouer le lot
        {"id": "10", "name": "Analyste", "location": {"city": "Genève"}},
    ]}
    jobs = REGISTRY["smartrecruiters"].parse(payload)
    assert [j.title for j in jobs] == ["Analyste"]
