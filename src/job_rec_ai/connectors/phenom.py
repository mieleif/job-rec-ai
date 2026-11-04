"""Connecteur Phenom : les sites carrière « Phenom People » (P&G, PMI, Givaudan).

Un site Phenom est servi par pays et par langue (https://<site>/<pays>/<langue>/…). Les
pages contiennent leurs données dans une variable JavaScript, phApp.ddo, en JSON :
    GET <site>/<pays>/<langue>/search-results?qcountry=Switzerland&from=N   10 offres par page
    GET <site>/<pays>/<langue>/job/<id>/                                     l'annonce complète
On filtre la recherche sur la Suisse côté serveur (sinon : 900 offres P&G dans le monde),
puis sur le lieu de chaque offre. Le robots.txt de Phenom n'interdit que les widgets,
la candidature et le suivi. On n'archive que les champs utiles de l'annonce : son JSON
contient aussi des vecteurs d'embedding et la description découpée en morceaux.
"""

import json
import re

from job_rec_ai.connectors.base import (
    LocationFilter,
    build_jobs,
    envelope,
    get_html_or_skip,
    paginate,
    parse_date,
)
from job_rec_ai.http import PoliteClient
from job_rec_ai.models import Job
from job_rec_ai.text import clean_html

PAGE_SIZE = 10  # imposé par Phenom
MAX_PAGES = 50
COUNTRY = "Switzerland"
_DDO = re.compile(r"phApp\.ddo\s*=\s*(\{.*?\});\s*phApp\.", re.S)
_KEPT = ("jobId", "reqId", "title", "description", "location", "multi_location", "city",
         "country", "postedDate", "type")


def ddo(html: str) -> dict:
    """Le JSON phApp.ddo d'une page Phenom ({} s'il est absent)."""
    match = _DDO.search(html)
    return json.loads(match.group(1)) if match else {}


def _places(job: dict) -> list[str]:
    """Les lieux : du texte dans la liste, des objets dans l'annonce ({"location": …})."""
    places = job.get("multi_location") or [job.get("location") or ""]
    return [p.get("location") or "" if isinstance(p, dict) else p for p in places]


class PhenomConnector:
    name = "phenom"

    def fetch(self, board: str, company: str, client: PoliteClient,
              keep: LocationFilter) -> dict:
        site = board.rstrip("/")

        def page(offset: int) -> tuple[list, int]:
            html = client.get_html(f"{site}/search-results",
                                   params={"qcountry": COUNTRY, "from": offset, "s": 1})
            search = ddo(html).get("eagerLoadRefineSearch")
            if search is None:
                raise ValueError(f"pas de résultats Phenom dans {site}/search-results")
            return search.get("data", {}).get("jobs", []), search.get("totalHits", 0)

        postings = []
        for item in paginate(page, PAGE_SIZE, MAX_PAGES):
            if not any(keep(place) for place in _places(item)):
                continue
            url = f"{site}/job/{item['jobId']}/"
            raw = get_html_or_skip(client, url)
            job = ddo(raw).get("jobDetail", {}).get("data", {}).get("job") if raw else None
            if job:
                postings.append({"url": url, **{k: job.get(k) for k in _KEPT}})
        return envelope(self.name, company, board, postings)

    def parse(self, payload: dict) -> list[Job]:
        def to_fields(job: dict) -> dict:
            return {
                "title": job["title"],
                "url": job["url"],
                "location": " / ".join(_places(job)),
                "description": clean_html(job.get("description")),
                "posted_at": parse_date(job.get("postedDate")),
                "source_id": str(job["jobId"]),
                "employment_type": job.get("type"),
            }

        return build_jobs(payload, to_fields)
