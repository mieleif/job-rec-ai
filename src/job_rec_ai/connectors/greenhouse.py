"""Connecteur Greenhouse : API publique « Job Board », documentée, sans clé.

    GET https://boards-api.greenhouse.io/v1/boards/<board>/jobs?content=true
Une seule requête rapporte tout le board, descriptions comprises : pas de pagination
ni de requête par offre (à l'inverse de Workday). Le filtre de lieu s'applique donc
après coup, sur la liste complète.
"""

from job_rec_ai.connectors.base import LocationFilter, build_jobs, envelope, parse_date
from job_rec_ai.http import PoliteClient
from job_rec_ai.markdown import html_to_markdown
from job_rec_ai.models import Job
from job_rec_ai.text import clean_html

API = "https://boards-api.greenhouse.io/v1/boards"


def _location(job: dict) -> str:
    return (job.get("location") or {}).get("name") or ""


def _metadata(job: dict, name: str) -> str | None:
    """Les champs personnalisés (« Employment Type »…) vivent dans une liste clé/valeur."""
    for item in job.get("metadata") or []:
        if item.get("name") == name and isinstance(item.get("value"), str):
            return item["value"]
    return None


class GreenhouseConnector:
    name = "greenhouse"

    def fetch(self, board: str, company: str, client: PoliteClient,
              keep: LocationFilter) -> dict:
        data = client.get_json(f"{API}/{board}/jobs", params={"content": "true"})
        postings = [job for job in data.get("jobs", []) if keep(_location(job))]
        return envelope(self.name, company, board, postings)

    def parse(self, payload: dict) -> list[Job]:
        def to_fields(job: dict) -> dict:
            return {
                "title": job["title"],
                "url": job["absolute_url"],
                "location": _location(job),
                # HTML échappé (« &lt;p&gt; ») : clean_html sait le dés-échapper
                "description": clean_html(job.get("content")),
                "description_markdown": html_to_markdown(job.get("content")),
                # Greenhouse déclare la langue de l'annonce : elle primera sur la détection
                "language": job.get("language"),
                "posted_at": parse_date(job.get("first_published") or job.get("updated_at")),
                "source_id": str(job["id"]),
                "employment_type": _metadata(job, "Employment Type"),
            }

        return build_jobs(payload, to_fields)
