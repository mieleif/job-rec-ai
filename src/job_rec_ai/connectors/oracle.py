"""Connecteur Oracle Recruiting Cloud : le « Candidate Experience » d'Oracle HCM.

Chaque employeur a un site https://<pod>.oraclecloud.<tld>/hcmUI/CandidateExperience/<langue>/
sites/<site>, application JavaScript nourrie par l'API REST publique d'Oracle HCM :
    GET /hcmRestApi/resources/latest/recruitingCEJobRequisitions
        ?finder=findReqs;siteNumber=<site>,limit=25,offset=N    liste paginée, sans description
    GET /hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails
        ?finder=ById;Id="<id>",siteNumber=<site>               détail, avec la description
Comme pour Workday, une requête par offre retenue. La recherche est restreinte au pays cible
côté serveur (location=Switzerland : JPMorgan publie 7 000 offres, dont 16 en Suisse). Ces
hôtes ne publient pas de robots.txt.
"""

import re

from job_rec_ai.connectors.base import (
    LocationFilter,
    build_jobs,
    envelope,
    paginate,
    parse_date,
)
from job_rec_ai.geo import TARGET_COUNTRY
from job_rec_ai.http import PoliteClient
from job_rec_ai.models import Job
from job_rec_ai.text import clean_html

PAGE_SIZE = 25
MAX_PAGES = 200  # garde-fou : 5 000 offres
REST = "/hcmRestApi/resources/latest"
_SITE = re.compile(r"^(https://[^/]+)/hcmUI/CandidateExperience/[^/]+/sites/([^/?#]+)")
_TEXT_FIELDS = ("ExternalDescriptionStr", "ExternalResponsibilitiesStr",
                "ExternalQualificationsStr")


def site_of(board: str) -> tuple[str, str]:
    """URL du site carrière → (hôte, numéro de site).

    https://x.fa.ocs.oraclecloud.eu/hcmUI/CandidateExperience/en/sites/CX_1/requisitions
    → ("https://x.fa.ocs.oraclecloud.eu", "CX_1")
    """
    match = _SITE.match(board)
    if not match:
        raise ValueError(f"site Oracle introuvable dans {board!r}")
    return match.group(1), match.group(2)


def _locations(item: dict) -> list[str]:
    """Lieu principal, lieux secondaires et lieux de travail (villes), sans doublon."""
    names = [item.get("PrimaryLocation"),
             *(loc.get("Name") for loc in item.get("secondaryLocations") or []),
             *(loc.get("TownOrCity") for loc in item.get("workLocation") or [])]
    return list(dict.fromkeys(n for n in names if n))


class OracleConnector:
    name = "oracle"

    def fetch(self, board: str, company: str, client: PoliteClient,
              keep: LocationFilter) -> dict:
        host, site = site_of(board)

        def page(offset: int) -> tuple[list, int]:
            data = client.get_json(
                f"{host}{REST}/recruitingCEJobRequisitions",
                params={"onlyData": "true", "expand": "requisitionList.secondaryLocations",
                        "finder": f"findReqs;siteNumber={site},location={TARGET_COUNTRY},"
                                  f"limit={PAGE_SIZE},offset={offset},sortBy=POSTING_DATES_DESC"})
            result = (data.get("items") or [{}])[0]
            return result.get("requisitionList", []), result.get("TotalJobsCount", 0)

        postings = []
        for item in paginate(page, PAGE_SIZE, MAX_PAGES):
            # « Switzerland » seul ne situe rien : le détail dira la ville (workLocation)
            if not (any(keep(loc) for loc in _locations(item))
                    or item.get("PrimaryLocationCountry") == "CH"):
                continue
            data = client.get_json(
                f"{host}{REST}/recruitingCEJobRequisitionDetails",
                params={"onlyData": "true", "expand": "all",
                        "finder": f'ById;Id="{item["Id"]}",siteNumber={site}'})
            detail = (data.get("items") or [None])[0]
            if detail and keep(" / ".join(_locations(detail))):
                postings.append({**detail, "url": f"{host}/hcmUI/CandidateExperience/en/"
                                                  f"sites/{site}/job/{item['Id']}"})
        return envelope(self.name, company, board, postings)

    def parse(self, payload: dict) -> list[Job]:
        def to_fields(detail: dict) -> dict:
            return {
                "title": detail["Title"],
                "url": detail["url"],
                "location": " / ".join(_locations(detail)),
                "description": " ".join(clean_html(detail[f]) for f in _TEXT_FIELDS
                                        if detail.get(f)),
                "posted_at": parse_date(detail.get("ExternalPostedStartDate")),
                "source_id": str(detail["Id"]),
                "employment_type": detail.get("JobSchedule"),
            }

        return build_jobs(payload, to_fields)
