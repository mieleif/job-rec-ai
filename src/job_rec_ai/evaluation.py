"""Jeu d'évaluation : des offres notées 0/1/2 par une personne, et les métriques des méthodes.

Un jeu = une personne (fichier JSON à la racine de data/eval/ ou data/private/eval/ : tout
*.json y est lu comme un jeu ; les notes copiées depuis la page vont dans notes/) : ses
requêtes (CV, profil…) et ses jugements.

    {"person": "leif", "queries": {"cv": "data/private/cv.pdf", "profil": "data/private/profil.md"},
     "pooled_at": "2026-11-05", "pool": [url, …], "judgments": {url: 0 | 1 | 2}}

Échelle : 2 = je voudrais qu'on me la montre en tête ; 1 = pertinente en partie ;
0 = hors sujet. On juge l'ADÉQUATION au profil, pas le lieu ni le taux : ce sont des filtres,
ils changeront sans que le jugement change.

Quelles offres noter ? Pas celles qu'on choisit soi-même dans l'explorateur : on noterait
ce qu'on sait déjà trouver (biais de sélection), et une méthode qui trouve autre chose
paraîtrait mauvaise. Le standard (TREC) est le POOLING : l'union des top k de toutes les
méthodes comparées, plus des offres tirées au hasard (pour estimer ce que toutes ratent),
présentées mélangées et sans score (pour ne pas influencer le juge).
"""

import json
import math
import random
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from job_rec_ai import koans
from job_rec_ai.cv import read_cv
from job_rec_ai.recommend import document, rank
from job_rec_ai.text import tokenize

EVAL_DIRS = (Path("data/eval"), Path("data/private/eval"))  # public (personas) / privé (moi)
DEPTH = 10      # profondeur du pooling et des métriques (@10 : ce qu'on lit d'un coup d'œil)
RANDOM = 10     # offres tirées au hasard dans le pool
SEED = 13


@dataclass
class EvalSet:
    path: Path
    person: str
    queries: dict[str, str]  # nom → chemin du texte (CV, profil…)
    judgments: dict[str, int] = field(default_factory=dict)
    pool: list[str] = field(default_factory=list)
    pooled_at: str | None = None

    def texts(self) -> dict[str, str]:
        return {name: read_cv(Path(p)) for name, p in self.queries.items()}

    def save(self) -> None:
        data = {"person": self.person, "queries": self.queries, "pooled_at": self.pooled_at,
                "pool": self.pool, "judgments": self.judgments}
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n",
                             encoding="utf-8")


def load_sets(dirs=EVAL_DIRS) -> list[EvalSet]:
    sets = []
    for d in dirs:
        for path in sorted(Path(d).glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            sets.append(EvalSet(path=path, person=data["person"], queries=data["queries"],
                                judgments=data.get("judgments", {}),
                                pool=data.get("pool", []), pooled_at=data.get("pooled_at")))
    return sets


# --- les méthodes comparées : (offres, texte de la requête) → URL classées ------------------


def _random(jobs, text):
    urls = [j["url"] for j in jobs]
    random.Random(SEED).shuffle(urls)
    return urls


def _tfidf(jobs, text):
    """Cosinus TF-IDF (koans), IDF appris sur les offres + la requête."""
    weights = koans.tfidf([document(j) for j in jobs] + [tokenize(text)])
    query, docs = weights[-1], weights[:-1]
    q_norm = math.sqrt(sum(w * w for w in query.values()))

    def cos(doc):
        norm = math.sqrt(sum(w * w for w in doc.values()))
        dot = sum(w * doc.get(t, 0.0) for t, w in query.items())
        return dot / (norm * q_norm) if norm and q_norm else 0.0

    scores = [cos(d) for d in docs]
    return [jobs[i]["url"] for i in sorted(range(len(jobs)), key=lambda i: -scores[i])]


def _bm25(jobs, text):
    """Le système en production (`recommend`) : BM25, répétitions du CV gardées."""
    return [j["url"] for j in rank(jobs, text)]


def _bm25_unique(jobs, text):
    """BM25, chaque mot du CV compté une fois (« ia » ×9 compte 1 fois)."""
    return [j["url"] for j in rank(jobs, text, unique=True)]


METHODS = {"hasard": _random, "tfidf": _tfidf, "bm25": _bm25, "bm25-dédoublonné": _bm25_unique}


def runs(eval_set: EvalSet, jobs: list[dict]) -> dict[str, list[str]]:
    """Chaque méthode × chaque requête de la personne → classement complet (URL)."""
    return {f"{method} · {name}": fn(jobs, text)
            for name, text in eval_set.texts().items() for method, fn in METHODS.items()}


def build_pool(eval_set: EvalSet, jobs: list[dict], depth: int = DEPTH,
               n_random: int = RANDOM) -> list[str]:
    """Union des top `depth` de toutes les méthodes (hors hasard) + `n_random` offres au
    hasard, mélangées. Les offres déjà jugées sont gardées (le pool ne fait que grandir)."""
    pool = dict.fromkeys(eval_set.pool)
    for name, ranked in runs(eval_set, jobs).items():
        if not name.startswith("hasard"):
            pool.update(dict.fromkeys(ranked[:depth]))
    rng = random.Random(f"{SEED}-{eval_set.person}-{len(pool)}")
    others = [j["url"] for j in jobs if j["url"] not in pool]
    pool.update(dict.fromkeys(rng.sample(others, min(n_random, len(others)))))
    urls = list(pool)
    rng.shuffle(urls)
    return urls


# --- métriques -------------------------------------------------------------------------------


@dataclass
class Scores:
    run: str
    precision: float  # P@k, pertinent = note ≥ 1
    mrr: float        # rang du premier « 2 »
    ndcg: float       # nDCG@k, gain = note
    judged: float     # part du top k qui a été jugée : < 1 → métriques sous-estimées


def evaluate(eval_set: EvalSet, jobs: list[dict], k: int = DEPTH) -> list[Scores]:
    grades = eval_set.judgments
    relevant = {u for u, g in grades.items() if g >= 1}
    excellent = {u for u, g in grades.items() if g >= 2}
    return [Scores(run=name,
                   precision=koans.precision_at_k(ranked, relevant, k),
                   mrr=koans.mean_reciprocal_rank([(ranked, excellent)]),
                   ndcg=koans.ndcg_at_k(ranked, grades, k),
                   judged=sum(u in grades for u in ranked[:k]) / k)
            for name, ranked in runs(eval_set, jobs).items()]


def grade_counts(eval_set: EvalSet) -> Counter:
    return Counter(eval_set.judgments.values())


def new_set(path: Path, person: str, queries: dict[str, str]) -> EvalSet:
    path.parent.mkdir(parents=True, exist_ok=True)
    return EvalSet(path=path, person=person, queries=queries, pooled_at=date.today().isoformat())
