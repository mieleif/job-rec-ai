"""Connecteur careers.un.org : le portail de recrutement du Secrétariat des Nations Unies.

Le Secrétariat (ONUG, HCDH, OCHA, CNUCED, CEE-ONU… à Genève) publie toutes ses offres sur
un seul portail, une application JavaScript qui interroge :
    POST https://careers.un.org/api/public/opening/jo/list/filteredV2/en   liste paginée
La liste contient déjà la description : pas de requête par offre. Le site ne publie pas
de robots.txt. Le lieu est le « lieu d'affectation » (dutyStation), en majuscules : GENEVA.
Les agences (OMS, HCR, OIT…) ont chacune leur propre site : ce connecteur ne les voit pas.
"""

from job_rec_ai.connectors.base import (
    LocationFilter,
    build_jobs,
    envelope,
    paginate,
    parse_date,
)
from job_rec_ai.http import PoliteClient
from job_rec_ai.models import Job
from job_rec_ai.text import clean_html

PAGE_SIZE = 100
MAX_PAGES = 30
API = "/api/public/opening/jo/list/filteredV2/en"


def _stations(job: dict) -> list[str]:
    return [s.get("description", "") for s in job.get("dutyStation") or []]


class UnCareersConnector:
    name = "uncareers"

    def fetch(self, board: str, company: str, client: PoliteClient,
              keep: LocationFilter) -> dict:
        site = board.rstrip("/")

        def page(offset: int) -> tuple[list, int]:
            data = client.post_json(f"{site}{API}", {
                "filterConfig": {"keyword": ""},
                "pagination": {"page": offset // PAGE_SIZE, "itemPerPage": PAGE_SIZE,
                               "sortBy": "startDate", "sortDirection": -1},
            })["data"]
            return data.get("list", []), data.get("count", 0)

        postings = [job for job in paginate(page, PAGE_SIZE, MAX_PAGES)
                    if any(keep(s) for s in _stations(job))]
        return envelope(self.name, company, board, postings)

    def parse(self, payload: dict) -> list[Job]:
        site = payload["board"].rstrip("/")

        def to_fields(job: dict) -> dict:
            return {
                # postingTitle ajoute parfois un suffixe interne (« …, 15 ») : jobTitle d'abord
                "title": job["jobTitle"] or job["postingTitle"],
                "url": f"{site}/jobSearchDescription/{job['jobId']}?language=en",
                "location": " / ".join(_stations(job)),
                # pas de champ langue : « EN » est la langue du portail, pas celle de l'annonce
                "description": clean_html(job.get("jobDescription")),
                "posted_at": parse_date(job.get("startDate")),
                "source_id": str(job["jobId"]),
                # « Staff », « Intern », « Temporary »… : le type de recrutement
                "employment_type": (job.get("recrttype") or {}).get("name"),
            }

        return build_jobs(payload, to_fields)
