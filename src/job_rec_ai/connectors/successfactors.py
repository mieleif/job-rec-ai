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
from job_rec_ai.geo import is_switzerland, mentions_target_place
from job_rec_ai.http import PoliteClient
from job_rec_ai.models import Job
from job_rec_ai.text import clean_html, normalize

# Au-delà, on filtre sur le lieu écrit dans l'URL avant de télécharger les annonces
# (Nestlé : 2 000 annonces dans le monde pour une centaine en Suisse romande). En deçà,
# on télécharge tout : certaines URL ne contiennent pas le lieu (SIG).
FULL_SCAN_MAX = 300
_ENTRY = re.compile(r"<url>\s*<loc>([^<]+/job/[^<]+)</loc>(?:\s*<lastmod>([^<]+)</lastmod>)?")
_JOB_ID = re.compile(r"/(\d+)/?$")
# Un NPA romand en fin d'URL (Mediclinic : « …-Clinique-Cecil-Secretaire-Laus-1003 », la ville
# tronquée). 1000-1999 : GE, VD, FR, VS romand ; 2100-2999 : NE, JU, Jura bernois et Bienne.
# 2000-2099 (Neuchâtel) exclus : ce sont surtout des années (« Graduate-Program-2026 »)
_ROMAND_NPA = re.compile(r"-(1\d{3}|2[1-9]\d{2})$")
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


# Coop tronque parfois le canton à quatre lettres (« Colombier, Neuc », « Fully, Vala ») :
# on le complète quand il est le début d'un nom de canton romand
_CANTON_NAMES = ("Genève", "Vaud", "Fribourg", "Neuchâtel", "Valais", "Jura")


def full_region(region: str | None) -> str | None:
    """« Neuc » → « Neuchâtel » ; un nom complet ou inconnu est rendu tel quel."""
    if region and len(region) <= 4:
        prefix = normalize(region)
        for name in _CANTON_NAMES:
            if normalize(name).startswith(prefix) and normalize(name) != prefix:
                return name
    return region


def worth_fetching(slug: str) -> bool:
    """Pré-filtre sur l'URL : un lieu romand y figure, y compris un canton tronqué en
    dernier mot (Coop : « Colombier-Vendeur-Neuc ») ou un NPA romand (« …-Laus-1003 »).
    Grossier exprès : le verdict vient du lieu de l'annonce, une fois téléchargée."""
    last = slug.rsplit("-", 1)[-1]
    return (mentions_target_place(slug) or mentions_target_place(full_region(last))
            or bool(_ROMAND_NPA.search(slug)))


def location_of(page: JobPostingPage, url: str, title: str | None) -> str:
    """Le lieu de l'annonce : microdonnées si elles disent plus qu'un code pays, sinon l'URL."""
    address = page.prop("streetAddress") or ""
    if "," in address:  # « Fribourg, CH » ; « CH » seul ne situe rien
        return address
    # Coop : commune et canton à part (« Aclens », « Vaud ») ; la commune seule est
    # souvent inconnue de geo, le canton la situe. Un seul des deux (« CH ») : l'URL d'abord
    # le NPA devant le canton (« Clinique Cecil, CH-1003 Laus ») : il situe même une ville
    # tronquée ; préfixé « CH- » seulement si l'annonce se dit en Suisse (Mediclinic recrute
    # aussi en Afrique du Sud : « 2196 », c'est Sandton)
    postal = page.prop("postalCode")
    if postal and is_switzerland(page.prop("addressCountry")):
        postal = f"CH-{postal}"
    region = " ".join(p for p in (postal, full_region(page.prop("addressRegion"))) if p)
    place = ", ".join(p for p in (page.prop("addressLocality"), region) if p)
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
        # Un board avec un chemin ne garde que ses annonces dans le sitemap du site : Mediclinic
        # publie Hirslanden (/Hirslanden/job/…), l'Afrique du Sud et le Moyen-Orient ensemble
        parts = urlsplit(board.rstrip("/"))
        site = f"{parts.scheme}://{parts.netloc}"
        entries = [(url, lastmod) for url, lastmod
                   in sitemap_entries(client.get_html(f"{site}/sitemap.xml"))
                   if urlsplit(url).path.startswith(f"{parts.path}/")]
        if not entries:
            raise ValueError(f"aucune annonce de {board} dans {site}/sitemap.xml")
        prefilter = len(entries) > FULL_SCAN_MAX

        postings = []
        for url, lastmod in entries:
            if prefilter and not worth_fetching(_slug(url)):
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
