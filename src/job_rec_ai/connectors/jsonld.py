"""Connecteur générique pour les sites carrière « maison » balisés en JSON-LD.

Certains gros employeurs n'ont pas d'ATS commun et publient leurs offres sur leur propre
site (l'État de Genève). Écrire un scraper par site irait contre le principe « un
connecteur par ATS » ; mais quand le site balise ses annonces en schema.org JobPosting
(pour Google for Jobs), un seul connecteur suffit pour tous :
    GET <board>            la page qui liste les offres (liens vers <board>/<offre>)
    GET <board>/<offre>    l'annonce, avec son <script type="application/ld+json">
On archive le JSON-LD lui-même : c'est exactement ce que lit parse().
"""

import html
import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from job_rec_ai.connectors.base import (
    LocationFilter,
    build_jobs,
    envelope,
    get_html_or_skip,
    parse_date,
)
from job_rec_ai.connectors.schema_org import json_ld_job_posting
from job_rec_ai.http import PoliteClient
from job_rec_ai.models import Job
from job_rec_ai.text import clean_html

MAX_PAGES = 20  # pages de liste suivies via rel="next"
# Champs texte de JobPosting : certains sites y répartissent l'annonce, dans cet ordre de lecture
_TEXT_FIELDS = ("description", "responsibilities", "qualifications", "experienceRequirements",
                "educationRequirements", "skills", "jobBenefits")


def job_links(html: str, page_url: str, board: str) -> tuple[list[str], str | None]:
    """Les liens vers les annonces (un niveau sous le board), et la page suivante éventuelle."""
    soup = BeautifulSoup(html, "html.parser")
    prefix = board.rstrip("/") + "/"
    links = []
    for a in soup.find_all("a", href=True):
        url = urljoin(page_url, a["href"]).split("#")[0]
        rest = url.removeprefix(prefix)
        if rest != url and rest.strip("/") and "/" not in rest.strip("/") and url not in links:
            links.append(url)
    following = soup.find(["a", "link"], rel="next", href=True)
    return links, urljoin(page_url, following["href"]) if following else None


def _clean(text: str) -> str:
    """Entités parfois échappées deux fois (« &amp;#160; »), espaces invisibles (U+200B)."""
    text = html.unescape(html.unescape(text)).replace("\u200b", " ")
    return re.sub(r"\s+", " ", text).strip()


def location_text(job: dict) -> str:
    """jobLocation (un lieu ou une liste) → « Genève, GE, CH »."""
    places = job.get("jobLocation") or []
    texts = []
    for place in places if isinstance(places, list) else [places]:
        addresses = place.get("address", {}) if isinstance(place, dict) else {}
        # schema.org autorise une adresse texte, un objet, ou une liste des deux
        for address in addresses if isinstance(addresses, list) else [addresses]:
            if isinstance(address, str):
                texts.append(_clean(address))
            elif isinstance(address, dict):
                parts = (address.get("addressLocality"), address.get("addressRegion"),
                         address.get("addressCountry"))
                parts = [_clean(p.get("name", "") if isinstance(p, dict) else p or "")
                         for p in parts]
                texts.append(", ".join(p for p in parts if p))
    return " / ".join(t for t in texts if t)


class JsonLdConnector:
    name = "jsonld"

    def fetch(self, board: str, company: str, client: PoliteClient,
              keep: LocationFilter) -> dict:
        # Pas de filtre de lieu (keep) : un site maison ne publie que les postes de son
        # employeur, choisi parce qu'il est dans l'arc lémanique. Ses lieux sont d'ailleurs
        # souvent des adresses sans ville (« Place du Bourg-de-Four 1 ») : le canton viendra
        # de l'employeur (vue jobs_view).
        links, page_url = [], board
        for _ in range(MAX_PAGES):
            found, following = job_links(client.get_html(page_url), page_url, board)
            links += [url for url in found if url not in links]
            if not following or following == page_url:
                break
            page_url = following

        postings = []
        for url in links:
            page = get_html_or_skip(client, url)  # retirée entre la liste et l'annonce : None
            job = json_ld_job_posting(page) if page else None
            if job is not None:  # sinon : page liée mais qui n'est pas une annonce
                postings.append({"url": url, "ld": job})
        return envelope(self.name, company, board, postings)

    def parse(self, payload: dict) -> list[Job]:
        def to_fields(posting: dict) -> dict:
            job = posting["ld"]
            kind = job.get("employmentType")
            identifier = job.get("identifier")
            if isinstance(identifier, dict):
                identifier = identifier.get("value")
            return {
                "title": _clean(job["title"]),
                "url": posting["url"],
                "location": location_text(job),
                # clean_html décode une fois ; _clean rattrape les entités échappées deux fois
                "description": _clean(" ".join(clean_html(job[f]) for f in _TEXT_FIELDS
                                               if isinstance(job.get(f), str))),
                "posted_at": parse_date(job.get("datePosted")),
                "source_id": str(identifier or urlsplit(posting["url"]).path.rstrip("/")
                                 .rsplit("/", 1)[-1]),
                "employment_type": ", ".join(kind) if isinstance(kind, list) else kind,
            }

        return build_jobs(payload, to_fields)
