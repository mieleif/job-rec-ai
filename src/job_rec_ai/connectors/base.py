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
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Protocol

from pydantic import ValidationError

from job_rec_ai.http import PoliteClient
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


def build_jobs(rows, to_job: Callable[[dict], Job]) -> list[Job]:
    """Applique to_job à chaque offre brute, en écartant (et en comptant) les invalides.

    Une offre malformée ne doit pas faire échouer tout le lot : on la journalise et on
    continue. Le nombre d'offres rejetées est un indicateur de qualité à surveiller.
    """
    jobs, rejected = [], 0
    for row in rows:
        try:
            jobs.append(to_job(row))
        except (KeyError, TypeError, ValidationError) as exc:
            rejected += 1
            log.warning("offre ignorée : %s", exc)
    if rejected:
        log.warning("%d offre(s) rejetée(s) sur %d", rejected, rejected + len(jobs))
    return jobs
