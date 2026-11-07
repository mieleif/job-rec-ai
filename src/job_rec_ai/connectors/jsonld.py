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
import logging
import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

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
from job_rec_ai.markdown import html_to_markdown, join_markdown
from job_rec_ai.models import Job
from job_rec_ai.text import clean_html, normalize

MAX_PAGES = 20  # pages de liste suivies via rel="next"
log = logging.getLogger(__name__)
# Paramètres de suivi, pas d'identité : l'URL d'une offre est sa clé en base. softgarden ajoute
# « jobDbPVId » (un identifiant de publication) : s'il change, la même offre aurait une autre URL
_TRACKING = re.compile(r"^(utm_\w+|jobdbpvid|gclid|fbclid|trk|src)$", re.I)
# Radancy et d'autres annoncent leur nombre de pages : de quoi voir une pagination non suivie
_TOTAL_PAGES = re.compile(r'data-total-pages="(\d+)"')


def canonical_url(url: str) -> str:
    """L'URL sans fragment ni paramètres de suivi (les autres, comme la langue, restent)."""
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not _TRACKING.match(k)]
    return urlunsplit(parts._replace(query=urlencode(query), fragment=""))
# Champs texte de JobPosting : certains sites y répartissent l'annonce, dans cet ordre de lecture
_TEXT_FIELDS = ("description", "responsibilities", "qualifications", "experienceRequirements",
                "educationRequirements", "skills", "jobBenefits")


def split_board(board: str) -> tuple[str, str | None]:
    """« <liste>#jobs=<chemin> » → (liste, chemin des annonces). Le fragment n'est jamais
    envoyé au serveur : il dit seulement où vivent les annonces quand ce n'est pas sous la
    liste (softgarden : liste /fr/vacancies, annonces /job/<id>/… ; Radancy : /en/job/…)."""
    url, _, fragment = board.partition("#")
    return url, fragment.removeprefix("jobs=") if fragment.startswith("jobs=") else None


def job_links(html: str, page_url: str, board: str) -> tuple[list[str], str | None]:
    """Les liens vers les annonces, et la page suivante éventuelle. Par défaut une annonce est
    un niveau sous la liste ; avec « #jobs=<chemin> », tout lien sous ce chemin du même site."""
    soup = BeautifulSoup(html, "html.parser")
    list_url, jobs_path = split_board(board)
    prefix = list_url.rstrip("/") + "/"
    site = urljoin(list_url, "/")
    links = []
    for a in soup.find_all("a", href=True):
        url = canonical_url(urljoin(page_url, a["href"]))
        if jobs_path:
            ok = url.startswith(site) and urlsplit(url).path.startswith(jobs_path)
        else:
            rest = url.removeprefix(prefix)
            ok = rest != url and rest.strip("/") and "/" not in rest.strip("/")
        if ok and url not in links:
            links.append(url)
    following = soup.find(["a", "link"], rel="next", href=True)
    return links, urljoin(page_url, following["href"]) if following else None


def listed_links(client: PoliteClient, board: str) -> list[str]:
    """Toutes les annonces listées sous le board, en suivant les pages rel="next"."""
    links, page_url = [], split_board(board)[0]
    announced = visited = 0
    for _ in range(MAX_PAGES):
        html = client.get_html(page_url)
        visited += 1
        announced = max([announced, *map(int, _TOTAL_PAGES.findall(html))])
        found, following = job_links(html, page_url, board)
        links += [url for url in found if url not in links]
        if not following or following == page_url:
            break
        page_url = following
    if announced > visited:  # pagination en JavaScript : des annonces ne sont pas vues
        log.warning("%s : %d pages annoncées, %d lues", board, announced, visited)
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


def _is_place_name(text: str) -> bool:
    """Un vrai nom de lieu : ni un simple pays, ni une rue (un numéro : « Place du
    Bourg-de-Four 1 »), ni un tiret (Vaudoise : « - »)."""
    return (bool(text) and normalize(text) not in _COUNTRY_ONLY
            and not any(c.isdigit() for c in text) and any(c.isalpha() for c in text))


def named_localities(job: dict) -> list[str]:
    """Les lieux donnés en champ structuré : la ville (addressLocality), à défaut la région
    (Vaudoise : « -, Zürich, Schweiz »). Vide pour une adresse texte : rien n'y est nommé."""
    places = job.get("jobLocation") or []
    found = []
    for place in places if isinstance(places, list) else [places]:
        addresses = place.get("address", {}) if isinstance(place, dict) else {}
        for address in addresses if isinstance(addresses, list) else [addresses]:
            if not isinstance(address, dict):
                continue
            for field in ("addressLocality", "addressRegion"):
                value = address.get(field)
                value = _clean(value.get("name", "") if isinstance(value, dict) else value or "")
                if re.fullmatch(r"[A-Z]{2}", value):  # code de canton nu : geo le veut entre ()
                    value = f"({value})"
                if _is_place_name(value):
                    found.append(value)
                    break
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
                "description_markdown": join_markdown(html_to_markdown(job[f])
                                                      for f in _TEXT_FIELDS
                                                      if isinstance(job.get(f), str)),
                "posted_at": parse_date(job.get("datePosted")),
                "source_id": str(identifier or urlsplit(posting["url"]).path.rstrip("/")
                                 .rsplit("/", 1)[-1]),
                "employment_type": ", ".join(kind) if isinstance(kind, list) else kind,
            }

        return build_jobs(payload, to_fields)
