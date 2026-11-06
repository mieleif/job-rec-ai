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
import logging
import math
import random
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from job_rec_ai import koans
from job_rec_ai.bm25 import BM25
from job_rec_ai.cv import read_cv
from job_rec_ai.recommend import document, rank
from job_rec_ai.text import tokenize

log = logging.getLogger(__name__)

EVAL_DIRS = (Path("data/eval"), Path("data/private/eval"))  # public (personas) / privé (moi)
DEPTH = 10      # profondeur du pooling et des métriques (@10 : ce qu'on lit d'un coup d'œil)
RANDOM = 10     # offres tirées au hasard dans le pool
SEED = 13
GRADES = (0, 1, 2)


@dataclass
class EvalSet:
    path: Path
    person: str
    queries: dict[str, str]  # nom → chemin du texte (CV, profil…)
    judgments: dict[str, int] = field(default_factory=dict)
    pool: list[str] = field(default_factory=list)
    drawn: list[str] = field(default_factory=list)  # la part du pool tirée au hasard
    pooled_at: str | None = None

    def texts(self) -> dict[str, str]:
        return {name: read_cv(Path(p)) for name, p in self.queries.items()}

    def save(self) -> None:
        data = {"person": self.person, "queries": self.queries, "pooled_at": self.pooled_at,
                "pool": self.pool, "random": self.drawn, "judgments": self.judgments}
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n",
                             encoding="utf-8")


def load_sets(dirs=EVAL_DIRS) -> list[EvalSet]:
    """Les jeux des dossiers d'évaluation. Un JSON qui n'est pas un jeu (pas de « person » ni
    de « queries » : un export, une sauvegarde) est ignoré avec un avertissement."""
    sets = []
    for d in dirs:
        for path in sorted(Path(d).glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not {"person", "queries"} <= data.keys():
                log.warning("%s ignoré : ce n'est pas un jeu d'évaluation", path)
                continue
            sets.append(EvalSet(path=path, person=data["person"], queries=data["queries"],
                                judgments=data.get("judgments", {}),
                                pool=data.get("pool", []), drawn=data.get("random", []),
                                pooled_at=data.get("pooled_at")))
    return sets


def validate_grades(grades: dict) -> dict[str, int]:
    """{url: note} copié depuis la page → notes entières de l'échelle, sinon ValueError."""
    bad = {url: g for url, g in grades.items() if g not in GRADES}
    if bad:
        raise ValueError(f"notes hors de l'échelle {GRADES} : {bad}")
    return {url: int(g) for url, g in grades.items()}


# --- les méthodes comparées : (corpus, texte de la requête) → URL classées ------------------
# Pas de méthode « hasard » : son top k ne serait jamais jugé (score nul par construction).
# La part tirée au hasard du pool mesure ce plancher (random_baseline).


@dataclass
class Corpus:
    """Les offres découpées en mots et l'index BM25, construits une fois pour toutes les
    méthodes et toutes les requêtes."""
    jobs: list[dict]
    docs: list[list[str]]
    index: BM25

    @classmethod
    def of(cls, jobs: list[dict]) -> "Corpus":
        docs = [document(j) for j in jobs]
        return cls(jobs, docs, BM25(docs))


def _tfidf(corpus, text):
    """Cosinus TF-IDF (koans), IDF appris sur les offres + la requête."""
    jobs = corpus.jobs
    weights = koans.tfidf(corpus.docs + [tokenize(text)])
    query, docs = weights[-1], weights[:-1]
    q_norm = math.sqrt(sum(w * w for w in query.values()))

    def cos(doc):
        norm = math.sqrt(sum(w * w for w in doc.values()))
        dot = sum(w * doc.get(t, 0.0) for t, w in query.items())
        return dot / (norm * q_norm) if norm and q_norm else 0.0

    scores = [cos(d) for d in docs]
    return [jobs[i]["url"] for i in sorted(range(len(jobs)), key=lambda i: -scores[i])]


def _bm25(corpus, text):
    """Le système en production (`recommend`) : BM25, répétitions du CV gardées."""
    return [j["url"] for j in rank(corpus.jobs, text, index=corpus.index)]


def _bm25_unique(corpus, text):
    """BM25, chaque mot du CV compté une fois (« ia » ×9 compte 1 fois)."""
    return [j["url"] for j in rank(corpus.jobs, text, unique=True, index=corpus.index)]


METHODS = {"tfidf": _tfidf, "bm25": _bm25, "bm25-dédoublonné": _bm25_unique}


def runs(eval_set: EvalSet, corpus: Corpus) -> dict[str, list[str]]:
    """Chaque méthode × chaque requête de la personne → classement complet (URL)."""
    return {f"{method} · {name}": fn(corpus, text)
            for name, text in eval_set.texts().items() for method, fn in METHODS.items()}


def build_pool(eval_set: EvalSet, corpus: Corpus, depth: int = DEPTH,
               n_random: int = RANDOM) -> tuple[list[str], list[str]]:
    """(pool, part tirée au hasard). Pool = union des top `depth` de toutes les méthodes +
    `n_random` offres au hasard, mélangées. Les offres déjà dans le pool y restent (il ne
    fait que grandir) ; le hasard est complété jusqu'à `n_random`, pas retiré à chaque
    appel : relancer sans nouvelle méthode ne rajoute rien à noter."""
    pool = dict.fromkeys(eval_set.pool)
    for ranked in runs(eval_set, corpus).values():
        pool.update(dict.fromkeys(ranked[:depth]))
    if set(pool) == set(eval_set.pool) and len(eval_set.drawn) >= n_random:
        return list(eval_set.pool), list(eval_set.drawn)  # rien de neuf : ordre gardé
    rng = random.Random(f"{SEED}-{eval_set.person}-{len(pool)}")
    others = [j["url"] for j in corpus.jobs if j["url"] not in pool]
    drawn = rng.sample(others, min(max(0, n_random - len(eval_set.drawn)), len(others)))
    pool.update(dict.fromkeys(drawn))
    urls = list(pool)
    rng.shuffle(urls)
    return urls, eval_set.drawn + drawn


# --- métriques -------------------------------------------------------------------------------


@dataclass
class Scores:
    run: str
    precision: float  # P@k, pertinent = note ≥ 1
    mrr: float        # rang du premier « 2 »
    ndcg: float       # nDCG@k, gain = note
    judged: float     # part du top k qui a été jugée : < 1 → métriques sous-estimées


def evaluate(eval_set: EvalSet, corpus: Corpus, k: int = DEPTH) -> list[Scores]:
    grades = eval_set.judgments
    relevant = {u for u, g in grades.items() if g >= 1}
    excellent = {u for u, g in grades.items() if g >= 2}
    return [Scores(run=name,
                   precision=koans.precision_at_k(ranked, relevant, k),
                   mrr=koans.mean_reciprocal_rank([(ranked, excellent)]),
                   ndcg=koans.ndcg_at_k(ranked, grades, k),
                   judged=sum(u in grades for u in ranked[:k]) / k)
            for name, ranked in runs(eval_set, corpus).items()]


def random_baseline(eval_set: EvalSet) -> tuple[int, Counter]:
    """Notes des offres tirées au hasard : ce que donnerait un classement aveugle (P@10
    attendue ≈ part notée ≥ 1). Peu d'offres : un ordre de grandeur, pas une mesure fine."""
    graded = [eval_set.judgments[u] for u in eval_set.drawn if u in eval_set.judgments]
    return len(graded), Counter(graded)


def grade_counts(eval_set: EvalSet) -> Counter:
    return Counter(eval_set.judgments.values())


def new_set(path: Path, person: str, queries: dict[str, str]) -> EvalSet:
    path.parent.mkdir(parents=True, exist_ok=True)
    return EvalSet(path=path, person=person, queries=queries)


def today() -> str:
    return date.today().isoformat()
