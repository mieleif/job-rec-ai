"""Recommandation baseline (M3) : le CV comme requête BM25 sur les offres actives.

BM25 a été pensé pour des requêtes de 2 à 5 mots ; un CV en fait ~350, dont « et » ×15 et
« ia » ×9. Côté requête, BM25 ne sature rien : un mot répété dans le CV compte autant de
fois. On retire les mots-outils, mais on GARDE les répétitions : elles disent ce que le CV
met en avant. Mesuré le 05.11.2026 sur les 38 offres notées par Leif : nDCG@10 0,775 avec
répétitions, 0,662 dédoublonné (0,740 contre 0,617 avec le profil comme requête).
"""

from job_rec_ai.bm25 import BM25, K1, B
from job_rec_ai.text import STOPWORDS, tokenize


def document(job: dict) -> list[str]:
    return tokenize(f"{job['title']} {job['description']}")


def query_terms(text: str, unique: bool = False) -> list[str]:
    words = [w for w in tokenize(text) if w not in STOPWORDS]
    return list(dict.fromkeys(words)) if unique else words


def rank(jobs: list[dict], cv_text: str, unique: bool = False, k1: float = K1,
         b: float = B) -> list[dict]:
    """Toutes les offres, de la plus pertinente à la moins pertinente, avec leur score."""
    scores = BM25([document(j) for j in jobs], k1=k1, b=b).scores(query_terms(cv_text, unique))
    order = sorted(range(len(jobs)), key=lambda i: -scores[i])
    return [{**jobs[i], "score": float(scores[i])} for i in order]
