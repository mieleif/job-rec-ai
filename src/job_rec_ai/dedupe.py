"""Dédoublonnage des offres.

Deux offres sont considérées comme identiques si elles ont la même URL, ou la même
empreinte « entreprise + titre + lieu » après normalisation (casse, accents, espaces).
Le second cas attrape la même annonce publiée sous deux URL (deux sites carrière, ou
un ATS qui change d'identifiant). On garde toujours la première vue : l'ordre d'entrée
encode la priorité des sources.
"""

from job_rec_ai.models import Job
from job_rec_ai.text import normalize


def fingerprint(job: Job) -> tuple[str, str, str]:
    return normalize(job.company), normalize(job.title), normalize(job.location)


def dedupe(jobs: list[Job]) -> list[Job]:
    seen_urls: set[str] = set()
    seen_prints: set[tuple[str, str, str]] = set()
    kept = []
    for job in jobs:
        url, print_ = str(job.url), fingerprint(job)
        if url in seen_urls or print_ in seen_prints:
            continue
        seen_urls.add(url)
        seen_prints.add(print_)
        kept.append(job)
    return kept
