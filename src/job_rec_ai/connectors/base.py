"""Ce que doit savoir faire un connecteur ATS : fetch (réseau) et parse (pur, testable).

Séparer les deux est le cœur du design : fetch rapporte la réponse brute de l'ATS telle
quelle (on la garde, c'est la couche « bronze »), parse la transforme en Job sans aucun
accès réseau. On peut donc rejouer parse sur des réponses archivées, et le tester sur des
fixtures, sans jamais toucher au réseau.

Le payload est une enveloppe autour des réponses brutes de l'ATS :
    {"ats": ..., "company": ..., "board": ..., "fetched_at": ..., "postings": [...]}
« company » est NOTRE nom canonique (celui de data/companies.csv), pas l'entité légale
renvoyée par l'ATS (« Novartis Pharma AG ») : c'est lui qui sert aux facettes.
"""

import logging
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime
from typing import Protocol

import httpx
from pydantic import ValidationError

from job_rec_ai.http import DisallowedByRobots, PoliteClient
from job_rec_ai.models import Job

log = logging.getLogger(__name__)

# Filtre sur le texte de lieu, appliqué AVANT de télécharger le détail des offres :
# inutile de demander 2 000 fiches Novartis pour en garder 30.
LocationFilter = Callable[[str | None], bool]


class Connector(Protocol):
    name: str

    def fetch(self, board: str, company: str, client: PoliteClient,
              keep: LocationFilter) -> dict: ...

    def parse(self, payload: dict) -> list[Job]: ...


def envelope(ats: str, company: str, board: str, postings: list) -> dict:
    return {"ats": ats, "company": company, "board": board,
            "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "postings": postings}


def parse_date(value) -> date | None:
    """« 2024-05-01 » ou « 2024-05-01T10:00:00.000Z » → date ; None si illisible."""
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def paginate(fetch_page: Callable[[int], tuple[list, int]], page_size: int,
             max_pages: int) -> Iterator[dict]:
    """Parcourt une liste paginée par offset. fetch_page(offset) → (offres, total).

    Le total n'est lu que s'il est non nul (Workday ne le renvoie qu'en première page) ;
    max_pages est un garde-fou contre une API qui paginerait à l'infini.
    """
    total = 0
    for page in range(max_pages):
        items, page_total = fetch_page(page * page_size)
        total = total or page_total
        yield from items
        if not items or (page + 1) * page_size >= total:
            break


def get_html_or_skip(client: PoliteClient, url: str) -> str | None:
    """Une page d'annonce, ou None si elle a disparu (4xx) ou est interdite par robots.txt.

    Une annonce retirée mais encore listée ne doit pas faire perdre toutes les autres ;
    une panne du site (réseau, 5xx persistants), elle, remonte : mieux vaut une collecte
    en erreur qu'une collecte vide, qui expirerait toutes les offres de l'employeur.
    """
    try:
        return client.get_html(url)
    except (httpx.HTTPStatusError, DisallowedByRobots) as exc:
        if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code >= 500:
            raise
        log.warning("annonce ignorée %s : %s", url, exc)
        return None


def build_jobs(payload: dict, to_fields: Callable[[dict], dict]) -> list[Job]:
    """Transforme chaque offre brute en Job, en écartant (et en comptant) les invalides.

    to_fields ne s'occupe que des champs propres à l'ATS ; la provenance (entreprise
    canonique, source) est tamponnée ici, une fois pour tous les connecteurs, car le
    stockage en dépend (expiration par entreprise et par source).

    Une offre malformée ne doit pas faire échouer tout le lot : on la journalise et on
    continue. Le nombre d'offres rejetées est un indicateur de qualité à surveiller.
    """
    provenance = {"company": payload["company"], "source": payload["ats"]}
    jobs, rejected = [], 0
    for row in payload.get("postings", []):
        try:
            jobs.append(Job(**to_fields(row), **provenance))
        except (KeyError, TypeError, ValidationError) as exc:
            rejected += 1
            log.warning("offre ignorée : %s", exc)
    if rejected:
        log.warning("%d offre(s) rejetée(s) sur %d", rejected, rejected + len(jobs))
    return jobs
