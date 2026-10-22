"""Connecteur SmartRecruiters : API publique et documentée, sans clé.

    GET https://api.smartrecruiters.com/v1/companies/<id>/postings   liste (100 par page)
    GET https://api.smartrecruiters.com/v1/companies/<id>/postings/<postingId>   détail
La liste donne déjà un lieu structuré (ville, région, pays) : on filtre avant le détail.
"""

from job_rec_ai.connectors.base import LocationFilter, build_jobs, envelope, parse_date
from job_rec_ai.http import PoliteClient
from job_rec_ai.models import Job
from job_rec_ai.text import clean_html

API = "https://api.smartrecruiters.com/v1/companies"
PAGE_SIZE = 100
MAX_PAGES = 50
# Ordre de lecture d'une annonce SmartRecruiters
_SECTIONS = ("companyDescription", "jobDescription", "qualifications", "additionalInformation")


def location_text(location: dict | None) -> str:
    location = location or {}
    if location.get("fullLocation"):
        return location["fullLocation"]
    parts = (location.get("city"), location.get("region"), location.get("country"))
    return ", ".join(p for p in parts if p)


class SmartRecruitersConnector:
    name = "smartrecruiters"

    def fetch(self, board: str, company: str, client: PoliteClient,
              keep: LocationFilter) -> dict:
        postings = []
        for page in range(MAX_PAGES):
            data = client.get_json(f"{API}/{board}/postings",
                                   params={"limit": PAGE_SIZE, "offset": page * PAGE_SIZE})
            items = data.get("content", [])
            for item in items:
                if keep(location_text(item.get("location"))):
                    postings.append(client.get_json(f"{API}/{board}/postings/{item['id']}"))
            if not items or (page + 1) * PAGE_SIZE >= data.get("totalFound", 0):
                break
        return envelope(self.name, company, board, postings)

    def parse(self, payload: dict) -> list[Job]:
        company, board = payload["company"], payload["board"]

        def to_job(detail: dict) -> Job:
            sections = detail.get("jobAd", {}).get("sections", {})
            text = " ".join(clean_html(sections.get(key, {}).get("text")) for key in _SECTIONS)
            return Job(
                title=detail["name"],
                company=company,
                url=detail.get("postingUrl")
                or f"https://jobs.smartrecruiters.com/{board}/{detail['id']}",
                location=location_text(detail.get("location")),
                description=text.strip(),
                posted_at=parse_date(detail.get("releasedDate")),
                source=self.name,
                source_id=str(detail["id"]),
                employment_type=(detail.get("typeOfEmployment") or {}).get("label"),
            )

        return build_jobs(payload.get("postings", []), to_job)
