"""Connecteur Prospective (prospective.ch) : l'ATS suisse derrière jobs.helvetia.com.

Le site carrière est une application JavaScript qui interroge une API publique :
    GET https://ohws.prospective.ch/public/v1/medium/<medium>/jobs?lang=fr&limit=200&offset=N
    → {"total": 156, "jobs": [{"id", "viewkey", "title", "szas": {...}, "attributes": {...}}]}
Les champs « sza_* » sont structurés : ville, NPA, pays, introduction, tâches, exigences,
domaine d'activité, taux… Le texte reste dans la langue de l'annonce (lang ne traduit que
les libellés). L'annonce publique vit à https://ohws.prospective.ch/public/v1/jobs/<viewkey>.
Pas de date de publication dans l'API. Le board est l'URL du « medium » (le canal de
publication : Helvetia Suisse = 1005736).
"""

from job_rec_ai.connectors.base import LocationFilter, build_jobs, envelope, paginate
from job_rec_ai.geo import is_switzerland
from job_rec_ai.http import PoliteClient
from job_rec_ai.models import Job
from job_rec_ai.text import clean_html

PAGE_SIZE = 200
MAX_PAGES = 20
JOB_PAGE = "https://ohws.prospective.ch/public/v1/jobs"
# Les blocs de texte de l'annonce, dans l'ordre de lecture
_TEXT = ("sza_introduction", "sza_tasks", "sza_requirements", "sza_offer",
         "sza_company_profil")


def location_of(szas: dict) -> str:
    """« Rheinfelden, CH-4310 » : le NPA situe aussi une commune inconnue de geo."""
    city, zip_code = szas.get("sza_location.city"), szas.get("sza_location.zip")
    if zip_code and is_switzerland(szas.get("sza_location.country")):
        zip_code = f"CH-{zip_code}"
    return ", ".join(p for p in (city, zip_code) if p)


class ProspectiveConnector:
    name = "prospective"

    def fetch(self, board: str, company: str, client: PoliteClient,
              keep: LocationFilter) -> dict:
        def page(offset: int) -> tuple[list, int]:
            data = client.get_json(f"{board.rstrip('/')}/jobs",
                                   params={"lang": "fr", "limit": PAGE_SIZE, "offset": offset})
            return data.get("jobs", []), data.get("total", 0)

        postings = [job for job in paginate(page, PAGE_SIZE, MAX_PAGES)
                    if keep(location_of(job.get("szas") or {}))]
        return envelope(self.name, company, board, postings)

    def parse(self, payload: dict) -> list[Job]:
        def to_fields(job: dict) -> dict:
            szas = job.get("szas") or {}
            return {
                "title": szas.get("sza_title") or job["title"],
                "url": f"{JOB_PAGE}/{job['viewkey']}",
                "location": location_of(szas),
                "description": " ".join(clean_html(szas[k]) for k in _TEXT if szas.get(k)),
                "source_id": str(job["id"]),
                "employment_type": szas.get("sza_pensum"),
                "category": szas.get("sza_field_of_activity"),
                "level": szas.get("sza_role"),
            }

        return build_jobs(payload, to_fields)
