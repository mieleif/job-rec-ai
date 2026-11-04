"""Connecteur SuccessFactors : les sites carrière « Recruiting Marketing » des employeurs.

SAP SuccessFactors héberge un site par employeur (jobs.sicpa.com, careers.epfl.ch…), de
deux générations : l'ancienne sert son HTML, la récente le construit en JavaScript à partir
d'une API JSON sous /services/, que leur robots.txt interdit. Ce qui reste permis, et commun
aux deux générations :
    GET <site>/sitemap.xml               toutes les annonces (fait pour les moteurs de recherche)
    GET <site>/job/<Lieu>-<Titre>/<id>/  l'annonce, avec ses microdonnées schema.org
Les annonces de la génération récente n'ont ni lieu ni date en microdonnées : le lieu se lit
dans l'URL (ce qui précède le titre), la date dans le sitemap (<lastmod>, la date de dernière
modification : une approximation de la date de publication).
"""

import html
import re
from datetime import date
from urllib.parse import unquote, urlsplit

from job_rec_ai.connectors.base import (
    LocationFilter,
    build_jobs,
    envelope,
    get_html_or_skip,
    parse_date,
)
from job_rec_ai.connectors.schema_org import JobPostingPage
from job_rec_ai.geo import mentions_target_place
from job_rec_ai.http import PoliteClient
from job_rec_ai.models import Job
from job_rec_ai.text import clean_html, normalize

# Au-delà, on filtre sur le lieu écrit dans l'URL avant de télécharger les annonces
# (Nestlé : 2 000 annonces dans le monde pour une cinquantaine dans l'arc lémanique). En deçà,
# on télécharge tout : certaines URL ne contiennent pas le lieu (SIG).
FULL_SCAN_MAX = 300
_ENTRY = re.compile(r"<url>\s*<loc>([^<]+/job/[^<]+)</loc>(?:\s*<lastmod>([^<]+)</lastmod>)?")
_JOB_ID = re.compile(r"/(\d+)/?$")
# Date.toString() de Java : « Tue Nov 03 02:00:00 CET 2026 », quel que soit le fuseau
_JAVA_DATE = re.compile(r"^\w{3} (\w{3}) (\d{1,2}) \d{2}:\d{2}:\d{2} \S+ (\d{4})$")
_MONTHS = {m: i for i, m in enumerate(
    "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(), start=1)}


def sitemap_entries(xml: str) -> list[tuple[str, str | None]]:
    """sitemap.xml → [(URL de l'annonce, date de dernière modification)]."""
    return [(html.unescape(url), lastmod) for url, lastmod in _ENTRY.findall(xml)]


def _slug(url: str) -> str:
    """« …/job/Le-Grand-Saconnex-Stagiaire-graphiste-Gen%C3%A8/137/ » → « Le-Grand-Saconnex-… »"""
    path = unquote(urlsplit(url).path)
    return path.split("/job/", 1)[1].split("/", 1)[0] if "/job/" in path else ""


def _words(text: str) -> list[str]:
    return re.findall(r"\w+", text)


def location_from_url(url: str, title: str) -> str:
    """Le lieu est ce qui précède le titre dans l'URL.

    « Le-Grand-Saconnex-Stagiaire-graphiste-Genè » et le titre « Stagiaire graphiste Genève »
    → « Le Grand Saconnex ». On cherche où commencent les premiers mots du titre (l'URL
    tronque parfois la fin, d'où la comparaison sur un préfixe seulement).
    """
    words = _words(_slug(url))
    keys = [normalize(w) for w in words]
    head = [normalize(w) for w in _words(title)][:3]

    def title_starts_at(start: int) -> bool:
        pairs = list(zip(keys[start:], head))
        last = len(keys) - 1  # seul le dernier mot de l'URL peut être tronqué
        return bool(pairs) and all(k == h or (start + i == last and h.startswith(k))
                                   for i, (k, h) in enumerate(pairs))

    for start in range(len(keys)):
        if title_starts_at(start):
            return " ".join(words[:start])
    return ""


def location_of(page: JobPostingPage, url: str) -> str:
    """Le lieu de l'annonce : microdonnées si elles disent plus qu'un code pays, sinon l'URL."""
    address = page.prop("streetAddress") or ""
    if "," in address:  # « Fribourg, CH » ; « CH » seul ne situe rien
        return address
    return location_from_url(url, page.prop("title") or "") or address


def posted_on(value: str | None) -> date | None:
    """« Tue Nov 03 02:00:00 CET 2026 » (format Java, tout fuseau) ou ISO → date."""
    if not value:
        return None
    java = _JAVA_DATE.match(value.strip())
    if java and java.group(1) in _MONTHS:
        month, day, year = java.groups()
        return date(int(year), _MONTHS[month], int(day))
    return parse_date(value)


class SuccessFactorsConnector:
    name = "successfactors"

    def fetch(self, board: str, company: str, client: PoliteClient,
              keep: LocationFilter) -> dict:
        site = board.rstrip("/")
        entries = sitemap_entries(client.get_html(f"{site}/sitemap.xml"))
        if not entries:
            raise ValueError(f"aucune annonce dans {site}/sitemap.xml")
        prefilter = len(entries) > FULL_SCAN_MAX

        postings = []
        for url, lastmod in entries:
            if prefilter and not mentions_target_place(_slug(url)):
                continue
            raw = get_html_or_skip(client, url)  # retirée mais encore dans le sitemap : None
            if raw is None:
                continue
            page = JobPostingPage(raw)
            if keep(location_of(page, url)):
                postings.append({"url": url, "lastmod": lastmod, "html": page.markup()})
        return envelope(self.name, company, board, postings)

    def parse(self, payload: dict) -> list[Job]:
        def to_fields(posting: dict) -> dict:
            page = JobPostingPage(posting["html"])
            job_id = _JOB_ID.search(posting["url"])
            return {
                "title": page.prop("title"),
                "url": posting["url"],
                "location": location_of(page, posting["url"]),
                "description": " ".join(clean_html(str(t)) for t in page.tags("description")),
                "posted_at": posted_on(page.prop("datePosted")) or parse_date(posting["lastmod"]),
                "source_id": job_id.group(1) if job_id else None,
            }

        return build_jobs(payload, to_fields)
