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
import time
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import numpy as np

from job_rec_ai import embeddings, koans, search
from job_rec_ai.bm25 import BM25
from job_rec_ai.cv import for_api, read_cv
from job_rec_ai.recommend import document, rank
from job_rec_ai.rerank import CANDIDATES, rerank
from job_rec_ai.text import chunk_text, tokenize

log = logging.getLogger(__name__)

EVAL_DIRS = (Path("data/eval"), Path("data/private/eval"))  # public (personas) / privé (moi)
DEPTH = 10      # profondeur du pooling et des métriques (@10 : ce qu'on lit d'un coup d'œil)
RANDOM = 10     # offres tirées au hasard dans le pool
SEED = 13
RECALL_DEPTH = 50  # ce que l'entonnoir transmet au reranker
CHUNK_WORDS, CHUNK_OVERLAP = 200, 40
TRUNCATION = 512  # tokens par offre (reranker)
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
class Trace:
    """Ce qu'une recommandation coûte : durée de chaque étape (ms) et CHF. L'indexation des
    offres n'y est pas (payée une fois, amortie sur toutes les recommandations)."""
    steps: dict[str, float] = field(default_factory=dict)
    chf: float = 0.0

    @contextmanager
    def step(self, name: str):
        start = time.perf_counter()
        yield
        self.steps[name] = (time.perf_counter() - start) * 1000

    def add(self, name: str, call: embeddings.Call) -> None:
        """Un appel d'API : la durée et le coût du VRAI appel, même relu depuis le cache."""
        self.steps[name] = call.ms
        self.chf += call.chf


def passage(job: dict) -> str:
    """Le texte d'une offre pour les modèles. Une offre Coop n'a que son titre, répété dans
    sa description : on ne l'écrit qu'une fois."""
    title, description = job["title"].strip(), (job["description"] or "").strip()
    return f"{title}. {description}" if description and description != title else title


@dataclass
class Corpus:
    """Les offres découpées en mots et l'index BM25, construits une fois pour toutes les
    méthodes et toutes les requêtes ; les vecteurs, à la première méthode qui en a besoin."""
    jobs: list[dict]
    docs: list[list[str]]
    index: BM25
    _vectors: dict = field(default_factory=dict, repr=False)

    @property
    def urls(self) -> list[str]:
        return [j["url"] for j in self.jobs]

    def vectors(self, client, name: str) -> np.ndarray:
        """Un vecteur par offre."""
        if name not in self._vectors:
            self._vectors[name] = client.embed_documents(
                embeddings.EMBEDDERS[name], [passage(j) for j in self.jobs])
        return self._vectors[name]

    def chunks(self, client, name: str) -> tuple[np.ndarray, np.ndarray]:
        """(un vecteur par chunk, indice de l'offre de chaque chunk). Chaque chunk commence
        par le titre : un morceau de description seul ne dit plus de quel poste il parle."""
        key = name, "chunks"
        if key not in self._vectors:
            texts, owners = [], []
            for i, job in enumerate(self.jobs):
                body = passage(job).removeprefix(job["title"].strip()).lstrip(". ")
                parts = chunk_text(body, CHUNK_WORDS, CHUNK_OVERLAP) or [""]
                texts += [f"{job['title'].strip()}. {p}" if p else passage(job) for p in parts]
                owners += [i] * len(parts)
            matrix = client.embed_documents(embeddings.EMBEDDERS[name], texts)
            self._vectors[key] = matrix, np.array(owners)
        return self._vectors[key]

    @classmethod
    def of(cls, jobs: list[dict]) -> "Corpus":
        docs = [document(j) for j in jobs]
        return cls(jobs, docs, BM25(docs))


def _tfidf(corpus, text, trace):
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


def _bm25(corpus, text, trace):
    """Le système en production (`recommend`) : BM25, répétitions du CV gardées."""
    with trace.step("bm25"):
        return [j["url"] for j in rank(corpus.jobs, text, index=corpus.index)]


def _bm25_unique(corpus, text, trace):
    """BM25, chaque mot du CV compté une fois (« ia » ×9 compte 1 fois)."""
    return [j["url"] for j in rank(corpus.jobs, text, unique=True, index=corpus.index)]


METHODS = {"tfidf": _tfidf, "bm25": _bm25, "bm25-dédoublonné": _bm25_unique}


def api_methods(client, person: str, embedders=tuple(embeddings.EMBEDDERS),
                reranked: str | None = "qwen3-8b") -> dict:
    """Les méthodes qui passent par l'API : vecteurs, chunks, hybride, hybride + reranker.

    Les rerankers partent tous du même hybride (`reranked`), fixé avant de voir les chiffres :
    croiser 3 embeddings × 4 rerankers ferait surtout gonfler le pool à noter à la main."""

    def vectors(name):
        def method(corpus, text, trace):
            matrix = corpus.vectors(client, name)
            query, call = client.embed_query(embeddings.EMBEDDERS[name],
                                             for_api(text, [person]))
            trace.add("embedding", call)
            with trace.step("cosinus"):
                return search.cosine_search(corpus.urls, matrix, query)
        return method

    def chunked(name):
        def method(corpus, text, trace):
            matrix, owners = corpus.chunks(client, name)
            query, call = client.embed_query(embeddings.EMBEDDERS[name],
                                             for_api(text, [person]))
            trace.add("embedding", call)
            with trace.step("cosinus"):
                scores = search.max_by_document(search.cosine_scores(matrix, query), owners,
                                                len(corpus.jobs))
                return [corpus.jobs[i]["url"] for i in np.argsort(-scores, kind="stable")]
        return method

    def hybrid(name):
        def method(corpus, text, trace):
            rankings = [_bm25(corpus, text, trace), vectors(name)(corpus, text, trace)]
            with trace.step("rrf"):
                return search.hybrid(rankings)
        return method

    def funnel(base, model, max_tokens):
        def method(corpus, text, trace):
            ranked = base(corpus, text, trace)
            texts = {j["url"]: passage(j) for j in corpus.jobs}
            top, call = rerank(client, embeddings.RERANKERS[model], for_api(text, [person]),
                               ranked[:CANDIDATES], texts, max_tokens)
            trace.add("rerank", call)
            return top + ranked[CANDIDATES:]
        return method

    methods = {name: vectors(name) for name in embedders}
    if reranked in embedders:
        methods[f"{reranked}-chunks"] = chunked(reranked)
    methods |= {f"bm25+{name}": hybrid(name) for name in embedders}
    if reranked in embedders:
        for model in embeddings.RERANKERS:
            for max_tokens, suffix in ((None, ""), (TRUNCATION, f"@{TRUNCATION}")):
                methods[f"bm25+{reranked} > {model}{suffix}"] = funnel(
                    hybrid(reranked), model, max_tokens)
    return methods


def runs(eval_set: EvalSet, corpus: Corpus, methods: dict | None = None,
         traces: dict[str, Trace] | None = None) -> dict[str, list[str]]:
    """Chaque méthode × chaque requête de la personne → classement complet (URL). `traces`,
    si fourni, reçoit la latence et le coût de chacune."""
    out = {}
    traces = {} if traces is None else traces
    for name, text in eval_set.texts().items():
        for method, fn in (methods or METHODS).items():
            run = f"{method} · {name}"
            traces[run] = Trace()
            out[run] = fn(corpus, text, traces[run])
    return out


def build_pool(eval_set: EvalSet, corpus: Corpus, depth: int = DEPTH,
               n_random: int = RANDOM,
               methods: dict | None = None) -> tuple[list[str], list[str]]:
    """(pool, part tirée au hasard). Pool = union des top `depth` de toutes les méthodes +
    `n_random` offres au hasard, mélangées. Les offres déjà dans le pool y restent (il ne
    fait que grandir) ; le hasard est complété jusqu'à `n_random`, pas retiré à chaque
    appel : relancer sans nouvelle méthode ne rajoute rien à noter."""
    pool = dict.fromkeys(eval_set.pool)
    for ranked in runs(eval_set, corpus, methods).values():
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
    recall: float     # recall@50, relatif aux offres déjà notées ≥ 1
    trace: Trace      # latence par étape et coût d'une recommandation


def evaluate(eval_set: EvalSet, corpus: Corpus, k: int = DEPTH,
             methods: dict | None = None) -> list[Scores]:
    grades = eval_set.judgments
    traces: dict[str, Trace] = {}
    relevant = {u for u, g in grades.items() if g >= 1}
    excellent = {u for u, g in grades.items() if g >= 2}
    return [Scores(run=name,
                   precision=koans.precision_at_k(ranked, relevant, k),
                   mrr=koans.mean_reciprocal_rank([(ranked, excellent)]),
                   ndcg=koans.ndcg_at_k(ranked, grades, k),
                   judged=sum(u in grades for u in ranked[:k]) / k,
                   recall=koans.recall_at_k(ranked, relevant, RECALL_DEPTH),
                   trace=traces[name])
            for name, ranked in runs(eval_set, corpus, methods, traces).items()]


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
