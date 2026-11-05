"""Connecteur Cornerstone OnDemand (csod.com) : le site carrière public d'un employeur.

    GET  https://<client>.csod.com/ux/ats/careersite/<site>/home?c=<client>
         la page publique ; elle contient `csod.context`, avec un jeton anonyme de courte
         durée et l'adresse de l'API (« cloud » : uk.api.csod.com en Europe)
    POST <cloud>/rec-job-search/external/jobs    recherche paginée
C'est exactement ce que fait le navigateur d'un visiteur : on lit le jeton dans la page, on
appelle l'API avec. La recherche renvoie déjà la description : pas de requête par offre.
Le filtre par pays du serveur suppose que l'employeur renseigne le pays : Groupe Mutuel ne
donne que ville et canton (« Martigny, VS »). Un petit board est donc lu en entier et filtré
ici ; un grand (MSC : des milliers d'offres dans le monde) est filtré sur la Suisse par le
serveur.
Le board est l'URL de la page carrière (MSC : https://msc.csod.com/ux/ats/careersite/4/home).
"""

import json
import re
from datetime import date, datetime
from urllib.parse import urlsplit

from job_rec_ai.connectors.base import LocationFilter, build_jobs, envelope, paginate
from job_rec_ai.http import PoliteClient
from job_rec_ai.models import Job
from job_rec_ai.text import clean_html

PAGE_SIZE = 50
MAX_PAGES = 20
_CONTEXT = re.compile(r"csod\.context\s*=\s*(\{.*?\});", re.S)
_SITE = re.compile(r"/careersite/(\d+)")


def site_of(board: str) -> tuple[str, str, int]:
    """URL de la page carrière → (origine, client, numéro de site)."""
    parts = urlsplit(board)
    return f"{parts.scheme}://{parts.netloc}", parts.netloc.split(".")[0], \
        int(_SITE.search(parts.path).group(1))


def _places(job: dict) -> list[str]:
    return [", ".join(p for p in (place.get("city"), place.get("state"), place.get("country"))
                      if p) for place in job.get("locations") or []]


def posted_on(value: str | None, culture: str) -> date | None:
    """« 04/11/2026 » : jour/mois en en-GB, mois/jour en en-US (la culture du site)."""
    if not value or value == "-":
        return None
    try:
        return datetime.strptime(value, "%m/%d/%Y" if culture == "en-US" else "%d/%m/%Y").date()
    except ValueError:
        return None


class CornerstoneConnector:
    name = "cornerstone"

    def fetch(self, board: str, company: str, client: PoliteClient,
              keep: LocationFilter) -> dict:
        origin, tenant, site = site_of(board)
        page = client.get_html(f"{origin}/ux/ats/careersite/{site}/home?c={tenant}")
        match = _CONTEXT.search(page)
        if not match:
            raise ValueError(f"pas de csod.context dans la page carrière de {tenant}")
        context = json.loads(match.group(1))
        api = f"{context['endpoints']['cloud'].rstrip('/')}/rec-job-search/external/jobs"
        headers = {"Authorization": f"Bearer {context['token']}"}

        countries: list[str] = []

        def page(offset: int) -> tuple[list, int]:
            data = client.post_json(api, {
                "careerSiteId": site, "careerSitePageId": site,
                "pageNumber": offset // PAGE_SIZE + 1, "pageSize": PAGE_SIZE,
                "cultureId": context["cultureID"], "cultureName": context["cultureName"],
                "searchText": "", "states": [], "countryCodes": countries, "cities": [],
                "placeID": "", "radius": None, "postingsWithinDays": None,
                "customFieldCheckboxKeys": [], "customFieldDropdowns": [],
                "customFieldRadios": [],
            }, headers=headers)["data"]
            return data.get("requisitions", []), data.get("totalCount", 0)

        first = page(0)
        if first[1] > PAGE_SIZE * MAX_PAGES:  # trop grand pour tout lire : le serveur filtre
            countries.append("ch")
            first = None

        def cached(offset: int) -> tuple[list, int]:  # la 1re page déjà lue n'est pas redemandée
            return first if offset == 0 and first else page(offset)

        postings = [job for job in paginate(cached, PAGE_SIZE, MAX_PAGES)
                    if any(keep(p) for p in _places(job))]
        payload = envelope(self.name, company, board, postings)
        payload["culture"] = context["cultureName"]  # pour lire les dates (jour/mois ou l'inverse)
        return payload

    def parse(self, payload: dict) -> list[Job]:
        origin, tenant, site = site_of(payload["board"])
        culture = payload.get("culture", "en-GB")

        def to_fields(job: dict) -> dict:
            rid = job["requisitionId"]
            return {
                "title": job["displayJobTitle"],
                "url": f"{origin}/ux/ats/careersite/{site}/home/requisition/{rid}?c={tenant}",
                "location": " / ".join(_places(job)),
                "description": clean_html(job.get("externalDescription")),
                "posted_at": posted_on(job.get("postingEffectiveDate"), culture),
                "source_id": str(rid),
            }

        return build_jobs(payload, to_fields)
