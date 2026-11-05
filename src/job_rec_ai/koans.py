"""Les briques de M3, écrites à la main pour les comprendre (sans scikit-learn).

Contrat : checkpoints/test_m3_baseline.py.
"""

import math
from collections import Counter

import numpy as np


def cosine_similarity(a, b) -> float:
    """cos θ = a·b / (‖a‖ ‖b‖) : l'angle entre deux vecteurs, indépendamment de leur longueur.

    Pour des comptes de mots (tous ≥ 0), le résultat est dans [0, 1] : 1 = même direction
    (même profil de vocabulaire, quelle que soit la longueur du texte), 0 = aucun mot commun.
    """
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    norms = np.linalg.norm(a) * np.linalg.norm(b)
    if norms == 0:  # un vecteur nul n'a pas de direction : l'angle n'est pas défini
        raise ValueError("similarité cosinus indéfinie pour un vecteur nul")
    return float(a @ b / norms)


def tfidf(docs: list[list[str]]) -> list[dict[str, float]]:
    """Poids TF-IDF de chaque mot de chaque document (documents déjà découpés en mots).

    tf = occurrences / nombre de mots du document : la part du document qu'occupe le mot.
    idf = ln(N / df), df = nombre de documents qui contiennent le mot : un mot présent
    partout (« et ») vaut ln(1) = 0, un mot rare vaut beaucoup. Le produit dit « ce mot est
    fréquent ICI mais rare AILLEURS » : c'est ce qui caractérise un document.
    """
    n = len(docs)
    df = Counter(word for doc in docs for word in set(doc))
    idf = {word: math.log(n / count) for word, count in df.items()}
    return [{word: count / len(doc) * idf[word] for word, count in Counter(doc).items()}
            for doc in docs]
