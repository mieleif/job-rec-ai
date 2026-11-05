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
from job_rec_ai.text import clean_html, normalize

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


def listed_links(client: PoliteClient, board: str) -> list[str]:
    """Toutes les annonces listées sous le board, en suivant les pages rel="next"."""
    links, page_url = [], board
    for _ in range(MAX_PAGES):
        found, following = job_links(client.get_html(page_url), page_url, board)
        links += [url for url in found if url not in links]
        if not following or following == page_url:
            break
        page_url = following
    return links


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


# Une « ville » qui n'est qu'un pays ne situe rien (CSEM : addressLocality « Switzerland »)
_COUNTRY_ONLY = {"switzerland", "suisse", "schweiz", "svizzera", "ch"}


def named_localities(job: dict) -> list[str]:
    """Les villes données en champ structuré (addressLocality), hors simple nom de pays.
    Vide pour une adresse texte (« Place du Bourg-de-Four 1 ») : le lieu n'y est pas nommé."""
    places = job.get("jobLocation") or []
    found = []
    for place in places if isinstance(places, list) else [places]:
        addresses = place.get("address", {}) if isinstance(place, dict) else {}
        for address in addresses if isinstance(addresses, list) else [addresses]:
            if isinstance(address, dict) and isinstance(address.get("addressLocality"), str):
                locality = _clean(address["addressLocality"])
                # un numéro = une rue mise dans le champ ville (« Place du Bourg-de-Four 1 »)
                if (locality and normalize(locality) not in _COUNTRY_ONLY
                        and not any(c.isdigit() for c in locality)):
                    found.append(locality)
    return found


class JsonLdConnector:
    name = "jsonld"

    def fetch(self, board: str, company: str, client: PoliteClient,
              keep: LocationFilter) -> dict:
        # Filtre de lieu (keep) seulement quand l'annonce NOMME sa ville (addressLocality) :
        # un employeur multi-sites (CSEM : Neuchâtel, Alpnach, Allschwil) publie aussi hors de
        # Suisse romande. Une adresse texte sans ville (État de Genève : « Place du
        # Bourg-de-Four 1 ») est gardée : le canton viendra de l'employeur (vue jobs_view).
        postings = []
        for url in listed_links(client, board):
            page = get_html_or_skip(client, url)  # retirée entre la liste et l'annonce : None
            job = json_ld_job_posting(page) if page else None
            if job is None:  # page liée mais qui n'est pas une annonce
                continue
            places = named_localities(job)
            if not places or any(keep(place) for place in places):
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
