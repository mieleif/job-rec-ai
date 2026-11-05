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
# (Nestlé : 2 000 annonces dans le monde pour une centaine en Suisse romande). En deçà,
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


# Les champs « libellé : valeur » de la fiche, hors microdonnées. Coop n'écrit pas de
# description (le bloc ne répète que le titre) mais renseigne ces champs :
#   Poste : Collaborateur · Spécialisation professionnelle : Vente Food · Taux d'occupation : …
# Les libellés dépendent du site et de la langue : on archive tout, on n'interprète que
# ceux qu'on connaît.
CATEGORY_LABELS = ("Spécialisation professionnelle", "Fachrichtung", "Job Function")
LEVEL_LABELS = ("Poste", "Position", "Stelle")


def details_of(page: JobPostingPage) -> dict[str, str]:
    """{libellé: valeur} des champs de la fiche (span data-careersite-propertyid précédé
    de son libellé). Les champs sans libellé (titre, description) sont déjà lus ailleurs."""
    details = {}
    for value in page.soup.select("[data-careersite-propertyid]"):
        label = value.find_previous_sibling()
        if label is None or "joblayouttoken-label" not in (label.get("class") or []):
            continue
        name, text = label.get_text(strip=True).rstrip(" :"), value.get_text(" ", strip=True)
        if name and text:
            details[name] = text
    return details


def _first(details: dict[str, str], labels: tuple[str, ...]) -> str | None:
    return next((details[label] for label in labels if label in details), None)


def title_of(page: JobPostingPage) -> str | None:
    """Le titre : microdonnées, à défaut la balise og:title (l'UIT n'a pas d'itemprop="title")."""
    return page.prop("title") or page.meta("og:title")


def location_of(page: JobPostingPage, url: str, title: str | None) -> str:
    """Le lieu de l'annonce : microdonnées si elles disent plus qu'un code pays, sinon l'URL."""
    address = page.prop("streetAddress") or ""
    if "," in address:  # « Fribourg, CH » ; « CH » seul ne situe rien
        return address
    # Coop : commune et canton à part (« Aclens », « Vaud ») ; la commune seule est
    # souvent inconnue de geo, le canton la situe. Un seul des deux (« CH ») : l'URL d'abord
    place = ", ".join(p for p in (page.prop("addressLocality"), page.prop("addressRegion")) if p)
    if "," in place:
        return place
    return location_from_url(url, title or "") or place or address


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
            title = title_of(page)  # hors microdonnées s'il vient d'og:title : on le garde à part
            if keep(location_of(page, url, title)):
                postings.append({"url": url, "lastmod": lastmod, "title": title,
                                 "html": page.markup(), "details": details_of(page)})
        return envelope(self.name, company, board, postings)

    def parse(self, payload: dict) -> list[Job]:
        def to_fields(posting: dict) -> dict:
            page = JobPostingPage(posting["html"])
            job_id = _JOB_ID.search(posting["url"])
            title = posting.get("title") or page.prop("title")  # archives d'avant « title »
            details = posting.get("details") or {}  # archives d'avant « details » : rien
            return {
                "title": title,
                "url": posting["url"],
                "location": location_of(page, posting["url"], title),
                "description": " ".join(clean_html(str(t)) for t in page.tags("description")),
                "posted_at": posted_on(page.prop("datePosted")) or parse_date(posting["lastmod"]),
                "source_id": job_id.group(1) if job_id else None,
                "category": _first(details, CATEGORY_LABELS),
                "level": _first(details, LEVEL_LABELS),
            }

        return build_jobs(payload, to_fields)
