"""Connecteur Workday : le plus répandu chez les grandes multinationales.

Les sites carrière Workday (https://<tenant>.wd<N>.myworkdayjobs.com/<site>) sont des
applications JavaScript qui appellent une API JSON interne, non documentée mais stable :
    POST /wday/cxs/<tenant>/<site>/jobs           liste paginée (20 offres max par page)
    GET  /wday/cxs/<tenant>/<site>/job/<chemin>   détail d'une offre (avec la description)
La liste ne contient ni description ni lieux complets : il faut une requête par offre.

Les grands boards (PwC : 3 800 offres dans le monde, une dizaine en Suisse romande) se
filtrent côté serveur par les facettes de recherche que renvoie l'API : le pays si le board
le propose, sinon les villes que reconnaît notre filtre de lieu. Le filtre de lieu reste
appliqué ensuite, offre par offre.
"""

import re
from urllib.parse import urlsplit

from job_rec_ai.connectors.base import (
    LocationFilter,
    build_jobs,
    envelope,
    paginate,
    parse_date,
)
from job_rec_ai.geo import TARGET_COUNTRY
from job_rec_ai.http import PoliteClient
from job_rec_ai.markdown import html_to_markdown
from job_rec_ai.models import Job
from job_rec_ai.text import clean_html

PAGE_SIZE = 20
MAX_PAGES = 250  # garde-fou : 5 000 offres
# Offre multi-sites : la liste affiche « 3 Locations », il faut le détail pour trancher
_MULTI = re.compile(r"^\d+\s+(locations|sites|lieux|standorte)$", re.IGNORECASE)
_LOCALE = re.compile(r"^[a-z]{2}-[A-Z]{2}$")


def api_base(board: str) -> str:
    """URL du site carrière → racine de l'API.

    https://acme.wd3.myworkdayjobs.com/en-US/Acme_Careers
    → https://acme.wd3.myworkdayjobs.com/wday/cxs/acme/Acme_Careers
    """
    parts = urlsplit(board)
    tenant = parts.netloc.split(".")[0]
    segments = [s for s in parts.path.split("/") if s and not _LOCALE.match(s)]
    if not segments:
        raise ValueError(f"site Workday introuvable dans {board!r}")
    return f"{parts.scheme}://{parts.netloc}/wday/cxs/{tenant}/{segments[0]}"


def _facet_values(facets: list[dict]) -> dict[str, list[dict]]:
    """Les facettes à plat : {"locationCountry": [{"id", "descriptor", "count"}…], …}.
    Workday les imbrique dans des groupes (« locationMainGroup » → « locations »)."""
    flat = {}
    for facet in facets:
        values = facet.get("values", [])
        flat.update(_facet_values([v for v in values if "values" in v]))
        leaves = [v for v in values if "id" in v]
        if leaves:
            flat[facet.get("facetParameter", "")] = leaves
    return flat


def target_facets(facets: list[dict], keep: LocationFilter) -> dict[str, list[str]] | None:
    """La facette qui restreint la recherche à nos lieux : le pays, sinon les villes.

    None : parcours complet. C'est aussi le cas d'une facette sans aucune valeur reconnue :
    elle ne prouve pas l'absence d'offre chez nous (pays traduit « Suisse », sites codés
    « CH-GVA-01 »), et conclure « rien ici » expirerait toutes les offres de l'employeur.
    """
    flat = _facet_values(facets)
    for name, matches in (("locationCountry", lambda d: d == TARGET_COUNTRY),
                          ("locations", keep)):
        ids = [v["id"] for v in flat.get(name, []) if matches(v.get("descriptor"))]
        if ids:
            return {name: ids}
    return None


def _locations(info: dict) -> list[str]:
    return [loc for loc in [info.get("location"), *info.get("additionalLocations", [])] if loc]


class WorkdayConnector:
    name = "workday"

    def fetch(self, board: str, company: str, client: PoliteClient,
              keep: LocationFilter) -> dict:
        api = api_base(board)

        def search(offset: int, facets: dict) -> dict:
            return client.post_json(f"{api}/jobs", {
                "appliedFacets": facets, "limit": PAGE_SIZE, "offset": offset, "searchText": "",
            })

        first = search(0, {})
        facets = target_facets(first.get("facets", []), keep)

        def page(offset: int) -> tuple[list, int]:
            # sans facette, la première page déjà reçue sert telle quelle
            data = first if offset == 0 and facets is None else search(offset, facets or {})
            return data.get("jobPostings", []), data.get("total", 0)

        postings = []
        for item in paginate(page, PAGE_SIZE, MAX_PAGES):
            where = item.get("locationsText", "")
            if not (keep(where) or _MULTI.match(where)):
                continue
            detail = client.get_json(f"{api}{item['externalPath']}")
            if any(keep(loc) for loc in _locations(detail.get("jobPostingInfo", {}))):
                postings.append(detail)
        return envelope(self.name, company, board, postings)

    def parse(self, payload: dict) -> list[Job]:
        def to_fields(detail: dict) -> dict:
            info = detail["jobPostingInfo"]
            return {
                "title": info["title"],
                "url": info["externalUrl"],
                "location": " / ".join(_locations(info)),
                "description": clean_html(info.get("jobDescription")),
                "description_markdown": html_to_markdown(info.get("jobDescription")),
                "posted_at": parse_date(info.get("startDate")),
                "source_id": info.get("jobReqId") or info.get("id"),
                "employment_type": info.get("timeType"),
            }

        return build_jobs(payload, to_fields)
