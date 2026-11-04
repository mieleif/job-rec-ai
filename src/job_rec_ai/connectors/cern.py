"""Connecteur CERN : le site carrière maison (WordPress), sans JSON-LD ni API publique.

Exception à la règle « un connecteur par ATS » : le CERN est l'un des plus gros employeurs
de Genève, et son site ne passe par aucun ATS lisible (la candidature part ensuite sur
SmartRecruiters, mais ses offres n'y sont pas listées). On lit :
    GET https://careers.cern/jobs/          la liste des annonces (liens un niveau sous /jobs/)
    GET https://careers.cern/jobs/<slug>/   l'annonce : <article class="job_offer">
Classes CSS d'un thème WordPress : moins stables que des microdonnées, d'où l'erreur
explicite si l'article disparaît (une collecte vide expirerait toutes les offres).
"""

from bs4 import BeautifulSoup

from job_rec_ai.connectors.base import LocationFilter, build_jobs, envelope, get_html_or_skip
from job_rec_ai.connectors.jsonld import job_links
from job_rec_ai.http import PoliteClient
from job_rec_ai.models import Job
from job_rec_ai.text import clean_html


def _text(article: BeautifulSoup, css: str) -> str:
    tag = article.select_one(css)
    return tag.get_text(" ", strip=True) if tag else ""


class CernConnector:
    name = "cern"

    def fetch(self, board: str, company: str, client: PoliteClient,
              keep: LocationFilter) -> dict:
        links, _ = job_links(client.get_html(board), board, board)
        postings, articles = [], 0
        for url in links:
            raw = get_html_or_skip(client, url)
            article = BeautifulSoup(raw, "html.parser").find("article") if raw else None
            if article is None:
                continue
            articles += 1
            if keep(_text(article, ".job-offer__header-infos .location")):
                postings.append({"url": url, "html": str(article)})  # l'article seul
        if links and not articles:
            raise ValueError(f"aucune annonce lisible sous {board} : le thème a changé ?")
        return envelope(self.name, company, board, postings)

    def parse(self, payload: dict) -> list[Job]:
        def to_fields(posting: dict) -> dict:
            article = BeautifulSoup(posting["html"], "html.parser")
            return {
                "title": _text(article, "h1"),
                "url": posting["url"],
                "location": _text(article, ".job-offer__header-infos .location"),
                "description": clean_html(str(article.select_one(".entry-content") or "")),
                "source_id": _text(article, ".job-offer__header-infos .ref") or None,
            }

        return build_jobs(payload, to_fields)
