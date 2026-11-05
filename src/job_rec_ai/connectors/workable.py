"""Connecteur Workable : l'API publique du widget « offres d'emploi » que les employeurs
intègrent sur leur site.

    GET https://apply.workable.com/api/v1/widget/accounts/<compte>?details=true
Une seule requête rapporte toutes les offres du compte, descriptions comprises (comme
Greenhouse) : le filtre de lieu s'applique après coup. Le lieu est structuré (ville,
canton, pays), avec une liste « locations » pour les offres multi-sites.
"""

from job_rec_ai.connectors.base import LocationFilter, build_jobs, envelope, parse_date
from job_rec_ai.http import PoliteClient
from job_rec_ai.models import Job
from job_rec_ai.text import clean_html

API = "https://apply.workable.com/api/v1/widget/accounts"


def _places(job: dict) -> list[str]:
    """« Lausanne, Vaud, Switzerland » pour chaque lieu de l'offre."""
    places = job.get("locations") or [job]
    return [", ".join(p for p in (place.get("city"), place.get("state"), place.get("country"))
                      if p) for place in places if isinstance(place, dict)]


class WorkableConnector:
    name = "workable"

    def fetch(self, board: str, company: str, client: PoliteClient,
              keep: LocationFilter) -> dict:
        data = client.get_json(f"{API}/{board}", params={"details": "true"})
        postings = [job for job in data.get("jobs", []) if any(keep(p) for p in _places(job))]
        return envelope(self.name, company, board, postings)

    def parse(self, payload: dict) -> list[Job]:
        def to_fields(job: dict) -> dict:
            return {
                "title": job["title"],
                "url": job["url"],
                "location": " / ".join(_places(job)),
                "description": clean_html(job.get("description")),
                "posted_at": parse_date(job.get("published_on") or job.get("created_at")),
                "source_id": job["shortcode"],
                "employment_type": job.get("employment_type") or None,
                "category": job.get("department") or None,
            }

        return build_jobs(payload, to_fields)
