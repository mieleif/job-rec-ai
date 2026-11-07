"""Connecteur CERN : le site carrière maison (WordPress), sans JSON-LD ni API publique.

Exception à la règle « un connecteur par ATS » : le CERN est l'un des plus gros employeurs
de Genève, et son site ne passe par aucun ATS lisible (la candidature part ensuite sur
SmartRecruiters, mais ses offres n'y sont pas listées). On lit :
    GET https://careers.cern/jobs/                 la liste (liens un niveau sous /jobs/)
    GET https://careers.cern/jobs/<slug>/          l'annonce : <article class="job_offer">
    GET https://careers.cern/jobs/feed/?paged=N    le flux RSS : la date de publication
Classes CSS d'un thème WordPress : moins stables que des microdonnées, d'où l'erreur
explicite si plus aucun article n'est lisible (une collecte vide expirerait les offres).
"""

import re
from email.utils import parsedate_to_datetime

from bs4 import BeautifulSoup

from job_rec_ai.connectors.base import (
    LocationFilter,
    build_jobs,
    envelope,
    get_html_or_skip,
    parse_date,
)
from job_rec_ai.connectors.jsonld import listed_links
from job_rec_ai.http import PoliteClient
from job_rec_ai.markdown import html_to_markdown
from job_rec_ai.models import Job
from job_rec_ai.text import clean_html

MAX_FEED_PAGES = 20  # 10 annonces par page de flux
_ITEM = re.compile(r"<item>.*?<link>([^<]+)</link>.*?<pubDate>([^<]+)</pubDate>", re.S)
# Ce que lit parse : on n'archive que ces parties de l'article (sans le gabarit autour)
_PARTS = ("h1", ".job-offer__header-infos", ".entry-content")


def _text(article: BeautifulSoup, css: str) -> str:
    tag = article.select_one(css)
    return tag.get_text(" ", strip=True) if tag else ""


def publication_dates(client: PoliteClient, board: str) -> dict[str, str]:
    """{URL de l'annonce: date ISO} d'après le flux RSS, page par page jusqu'à la dernière (404)."""
    dates = {}
    for page in range(1, MAX_FEED_PAGES + 1):
        feed = get_html_or_skip(client, f"{board.rstrip('/')}/feed/?paged={page}")
        items = _ITEM.findall(feed or "")
        for link, published in items:
            dates[link.strip()] = parsedate_to_datetime(published.strip()).date().isoformat()
        if not items:
            break
    return dates


class CernConnector:
    name = "cern"

    def fetch(self, board: str, company: str, client: PoliteClient,
              keep: LocationFilter) -> dict:
        links = [url for url in listed_links(client, board) if not url.endswith("/feed/")]
        postings, articles = [], 0
        for url in links:
            raw = get_html_or_skip(client, url)
            article = BeautifulSoup(raw, "html.parser").find("article") if raw else None
            if article is None:
                continue
            articles += 1
            if keep(_text(article, ".job-offer__header-infos .location")):
                parts = (article.select_one(css) for css in _PARTS)
                postings.append({"url": url, "html": "\n".join(str(p) for p in parts if p)})
        if links and not articles:
            raise ValueError(f"aucune annonce lisible sous {board} : le thème a changé ?")
        if postings:
            dates = publication_dates(client, board)
            for posting in postings:
                posting["published"] = dates.get(posting["url"])
        return envelope(self.name, company, board, postings)

    def parse(self, payload: dict) -> list[Job]:
        def to_fields(posting: dict) -> dict:
            article = BeautifulSoup(posting["html"], "html.parser")
            content = str(article.select_one(".entry-content") or "")
            return {
                "title": _text(article, "h1"),
                "url": posting["url"],
                "location": _text(article, ".job-offer__header-infos .location"),
                "description": clean_html(content),
                "description_markdown": html_to_markdown(content),
                "posted_at": parse_date(posting.get("published")),
                "source_id": _text(article, ".job-offer__header-infos .ref") or None,
            }

        return build_jobs(payload, to_fields)
