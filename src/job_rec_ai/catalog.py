"""Le catalogue d'offres servi par l'API (GET /jobs…) : identifiants, filtres, facettes, extraits.

Fonctions pures sur les offres déjà en mémoire (voir api.Index) : aucune requête SQL par appel.
Pourquoi en mémoire plutôt que du SQL à chaque recherche ? La collecte nocturne verrouille la
base (un seul processus DuckDB à la fois) : l'API doit répondre pendant ces ~75 minutes, avec
l'index de la veille. Et ~2 000 offres se filtrent en Python en une milliseconde.

L'identifiant public d'une offre est un condensé de son URL (la clé de la base) : court, stable
d'une collecte à l'autre, et sans exposer l'URL dans le chemin des pages de DoxAI.
"""

import hashlib
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta

from job_rec_ai.bm25 import BM25
from job_rec_ai.domains import company_key
from job_rec_ai.markdown import text_to_markdown
from job_rec_ai.recommend import document
from job_rec_ai.text import STOPWORDS, tokenize

SNIPPET = 240  # caractères au plus, « … » compris
LANGUAGES = ("fr", "de", "en", "it")
ID_PATTERN = re.compile(r"^[0-9a-f]{16}$")

# Détection de l'allemand et de l'italien pour le champ `language` de l'API seulement : la
# colonne `language` de la base (fr, en, other) et les mots-outils du moteur ne changent pas,
# sinon le classement de /recommend changerait aussi.
_STOPWORDS_DE_IT = {
    "de": {"der", "die", "das", "und", "mit", "für", "sie", "wir", "ihre", "unsere", "ist",
           "von", "zu", "auf", "eine", "ein", "im", "den", "bei", "sind", "werden", "nicht"},
    "it": {"il", "lo", "gli", "della", "delle", "degli", "del", "che", "per", "con", "una",
           "sono", "nel", "nella", "alla", "dei", "di", "ed", "anche", "questo", "siamo"},
}


def job_id(url: str) -> str:
    """Les 16 premiers caractères hexadécimaux du SHA-256 de l'URL : 64 bits, aucune
    collision à craindre pour quelques milliers d'offres (paradoxe des anniversaires :
    ~1 chance sur 10¹¹ pour 2 000 offres)."""
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def language_code(stored: str | None, text: str) -> str | None:
    """« fr », « de », « en », « it » ou None. La base ne distingue que fr / en / other
    (`text.detect_language`) ; « other » est précisé ici en allemand ou en italien."""
    code = re.split(r"[-_]", (stored or "").strip().lower())[0]
    if code in LANGUAGES:
        return code
    words = re.findall(r"[a-zà-ÿ]+", text.casefold())
    if len(words) < 3:
        return None
    scores = {lang: sum(w in stop for w in words) for lang, stop in _STOPWORDS_DE_IT.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] / len(words) >= 0.05 else None


def snippet(text: str, limit: int = SNIPPET) -> str:
    """Le début du texte, coupé sur une fin de mot avec « … » s'il est plus long que `limit`."""
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit - 1]  # une place gardée pour « … »
    if not text[limit - 1].isspace() and " " in cut:  # coupe au milieu d'un mot : on le retire
        cut = cut.rsplit(" ", 1)[0]
    return f"{cut.rstrip(' ,;:-–—(')}…"


def search_terms(text: str) -> list[str]:
    """Les mots d'une recherche, sans mots-outils ni doublons (« python python » ne compte
    pas double : ce n'est pas un CV qui insiste, c'est une saisie)."""
    return list(dict.fromkeys(w for w in tokenize(text) if w not in STOPWORDS))


def similar_terms(job: dict) -> list[str]:
    """La requête « offres semblables » : le titre et la description de l'offre, sans
    mots-outils ni nombres purs, répétitions gardées (comme un CV, voir recommend.py)."""
    return [w for w in document(job) if w not in STOPWORDS and any(c.isalpha() for c in w)]


def prepare(job: dict, domains: dict[str, str] | None = None) -> dict:
    """Une ligne de `storage.jobs_for_api` → l'offre telle que l'API la sert (id, domaine de
    l'employeur, langue, extrait, Markdown de repli). Les clés d'origine restent : /recommend
    les lit. `domains` : `storage.company_domains` (clé normalisée → domaine)."""
    text = job.get("description") or ""
    return {
        **job,
        "id": job_id(job["url"]),
        "company_domain": (domains or {}).get(company_key(job["company"])),
        "location": job.get("location") or "",
        "language_code": language_code(job.get("language"), f"{job['title']} {text}"),
        "snippet": snippet(text),
        # Sans HTML d'origine (ou pas encore rempli) : des paragraphes tirés du texte brut
        "markdown": job.get("description_markdown") or text_to_markdown(text),
    }


def summary(job: dict) -> dict:
    return {"id": job["id"], "url": job["url"], "title": job["title"],
            "company": job["company"], "company_domain": job["company_domain"],
            "location": job["location"], "canton": job["canton"],
            "workload_min": job["workload_min"], "workload_max": job["workload_max"],
            "posted_at": job["posted_at"], "language": job["language_code"],
            "employment_type": job["employment_type"], "family": job["family"],
            "snippet": job["snippet"]}


def detail(job: dict) -> dict:
    return {**summary(job), "description_markdown": job["markdown"],
            "description_text": job.get("description") or "", "category": job["category"],
            "seniority": job["seniority"], "source": job["source"]}


@dataclass
class Query:
    q: str | None = None
    cantons: frozenset[str] = frozenset()
    workload_min: int | None = None
    workload_max: int | None = None
    posted_within_days: int | None = None
    sort: str | None = None  # relevance | recent ; défaut : relevance s'il y a q, sinon recent
    page: int = 1
    per_page: int = 20


def _workload_overlaps(job: dict, low: int | None, high: int | None) -> bool:
    """Les plages se recouvrent. Une offre sans taux affiché est supposée à 100 % (comme
    `storage.search`) ; une borne seule vaut pour les deux."""
    job_low = job["workload_min"] if job["workload_min"] is not None else job["workload_max"]
    job_high = job["workload_max"] if job["workload_max"] is not None else job["workload_min"]
    job_low = 100 if job_low is None else job_low
    job_high = 100 if job_high is None else job_high
    return (low is None or job_high >= low) and (high is None or job_low <= high)


def _recent_key(job: dict) -> tuple:
    """Publiées les plus récentes d'abord, sans date à la fin ; puis vues en dernier, puis id
    (un ordre total : la pagination ne doit ni répéter ni sauter d'offre)."""
    posted = job["posted_at"]
    return (posted is None, _desc(posted or ""), _desc(job.get("first_seen") or ""), job["id"])


def _desc(value: str) -> tuple:
    """Clé de tri décroissante pour une date ISO « AAAA-MM-JJ » (même longueur pour toutes) :
    les codes des caractères, négatifs."""
    return tuple(-ord(c) for c in value)


def search(jobs: list[dict], index: BM25, query: Query, today: date) -> dict:
    """GET /jobs : filtre, facettes, tri et page. `index` : BM25 sur titre + entreprise +
    description, construit sur `jobs` dans le même ordre."""
    terms = search_terms(query.q or "")
    scores = index.scores(terms) if terms else None
    since = (today - timedelta(days=query.posted_within_days)).isoformat() \
        if query.posted_within_days is not None else None

    matching = []  # tous les filtres sauf les cantons : la base des facettes
    for i, job in enumerate(jobs):
        if scores is not None and scores[i] <= 0:
            continue
        if not _workload_overlaps(job, query.workload_min, query.workload_max):
            continue
        # Sans date de publication (Prospective n'en donne pas) : la date de première collecte
        if since and (job["posted_at"] or job.get("first_seen") or "") < since:
            continue
        matching.append((float(scores[i]) if scores is not None else 0.0, job))

    facets = Counter(job["canton"] for _, job in matching if job["canton"])
    hits = [(s, j) for s, j in matching if not query.cantons or j["canton"] in query.cantons]

    sort = query.sort or ("relevance" if scores is not None else "recent")
    if sort == "relevance" and scores is not None:
        hits.sort(key=lambda hit: (-hit[0], *_recent_key(hit[1])))
    else:
        hits.sort(key=lambda hit: _recent_key(hit[1]))

    start = (query.page - 1) * query.per_page
    return {
        "total": len(hits), "page": query.page, "per_page": query.per_page,
        "jobs": [summary(j) for _, j in hits[start:start + query.per_page]],
        "facets": {"cantons": dict(sorted(facets.items(), key=lambda kv: (-kv[1], kv[0])))},
    }


def similar(jobs: list[dict], index: BM25, position: int, k: int) -> list[dict]:
    """GET /jobs/{id}/similar : les k offres les plus proches (BM25 sur titre + description,
    l'index de /recommend), l'offre elle-même exclue, sans offre à score nul."""
    scores = index.scores(similar_terms(jobs[position]))
    order = sorted((i for i in range(len(jobs)) if i != position and scores[i] > 0),
                   key=lambda i: (-scores[i], jobs[i]["id"]))
    return [summary(jobs[i]) for i in order[:k]]


def search_document(job: dict) -> list[str]:
    """Le texte cherché par GET /jobs?q= : titre, entreprise et description."""
    return tokenize(f"{job['title']} {job['company']} {job.get('description') or ''}")
