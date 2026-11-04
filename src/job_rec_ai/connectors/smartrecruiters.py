"""Connecteur SmartRecruiters : le site carrière public, pas l'API.

L'API JSON (api.smartrecruiters.com) est interdite aux robots par son robots.txt
(seul LinkedIn y a droit). Les pages publiques, elles, ne publient pas de robots.txt :
par convention (RFC 9309), tout y est permis. On lit donc le HTML que voit un candidat :
    GET careers.smartrecruiters.com/<id>                    liste, 1re page (groupée par service)
    GET careers.smartrecruiters.com/<id>/api/groups?page=N  pages suivantes (fragments HTML)
    GET jobs.smartrecruiters.com/<id>/<offre>-<slug>        l'annonce
L'annonce est balisée en schema.org JobPosting (microdonnées itemprop="title",
"datePosted"…), le format que lit Google for Jobs : c'est sur lui qu'on s'appuie,
pas sur les classes CSS du gabarit, qui changent au gré des refontes.
"""

import re

from bs4 import BeautifulSoup

from job_rec_ai.connectors.base import LocationFilter, build_jobs, envelope, parse_date
from job_rec_ai.connectors.schema_org import JobPostingPage
from job_rec_ai.http import PoliteClient
from job_rec_ai.models import Job
from job_rec_ai.text import clean_html

CAREERS = "https://careers.smartrecruiters.com"
MAX_PAGES = 50  # garde-fou
_PAGES = re.compile(r'data-groups-pages="(\d+)"')
_JOB_URL = re.compile(r"^https://jobs\.smartrecruiters\.com/[^/]+/(\d+)")
# Sections de l'annonce sans texte utile (vidéos, carte). Retirées dès l'archivage : la carte
# embarque la clé Google Maps (publique) de SmartRecruiters, que les scanners de secrets
# de GitHub signalent.
_NOISE = ("st-videos", "st-embed-map")


def openings(html: str) -> list[tuple[str, str]]:
    """Une page de liste → [(URL de l'annonce, texte où chercher le lieu)].

    Chaque employeur choisit comment grouper sa liste : par service (HUG : le lieu est
    sur chaque offre) ou par lieu (Vitol : le lieu est l'en-tête du groupe, l'offre
    n'affiche que « Full-time »). On renvoie donc les deux, en-tête et détails de l'offre.
    """
    soup = BeautifulSoup(html, "html.parser")
    found = []
    for link in soup.find_all("a", href=_JOB_URL):
        group = link.find_parent("section")
        header = group.select_one(".opening-title") if group else None
        texts = [header.get_text(strip=True) if header else ""]
        texts += [span.get_text(strip=True) for span in link.select(".job-desc span")]
        found.append((link["href"], " · ".join(t for t in texts if t)))
    return found


def archived(html: str) -> str:
    """On n'archive que <main>, sans vidéos ni carte : l'annonce sans le gabarit de page."""
    start, end = html.find("<main"), html.find("</main>")
    if start >= 0 and end > start:
        html = html[start:end + len("</main>")]
    soup = BeautifulSoup(html, "html.parser")
    for section in soup.find_all("section", id=_NOISE):
        section.decompose()
    return str(soup)


class SmartRecruitersConnector:
    name = "smartrecruiters"

    def fetch(self, board: str, company: str, client: PoliteClient,
              keep: LocationFilter) -> dict:
        first = client.get_html(f"{CAREERS}/{board}")
        pages = _PAGES.search(first)
        if not pages:
            # Ex. : CERN redirige vers son propre site (careers.cern)
            raise ValueError(f"pas de liste SmartRecruiters pour {board!r} (redirection ?)")
        listing = openings(first)
        for page in range(1, min(int(pages.group(1)), MAX_PAGES)):
            listing += openings(client.get_html(f"{CAREERS}/{board}/api/groups",
                                                params={"page": page}))

        # Une offre peut figurer dans plusieurs groupes (un par lieu, chez Vitol) : elle passe
        # le filtre si l'un de ses lieux est dans l'arc lémanique
        wheres: dict[str, list[str]] = {}
        for url, where in listing:
            wheres.setdefault(url, []).append(where)
        postings = []
        for url, texts in wheres.items():
            if any(keep(where) for where in texts):
                postings.append({"id": _JOB_URL.match(url).group(1), "url": url,
                                 "html": archived(client.get_html(url))})
        return envelope(self.name, company, board, postings)

    def parse(self, payload: dict) -> list[Job]:
        def to_fields(posting: dict) -> dict:
            page = JobPostingPage(posting["html"])
            description = page.tag("description")
            place = (page.prop("addressLocality"), page.prop("addressRegion"),
                     page.prop("addressCountry"))
            return {
                "title": page.prop("title"),
                "url": posting["url"],
                "location": ", ".join(p for p in place if p),
                "description": clean_html(str(description) if description else None),
                "posted_at": parse_date(page.prop("datePosted")),
                "source_id": posting["id"],
                "employment_type": page.prop("employmentType"),
            }

        return build_jobs(payload, to_fields)
