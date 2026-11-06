"""BM25 (Okapi), écrit à la main : TF-IDF avec saturation et normalisation de longueur.

    score(Q, D) = Σ_{w ∈ Q} idf(w) · f(w,D)·(k1 + 1) / (f(w,D) + k1·(1 − b + b·|D|/avgdl))

- k1 : saturation. Le poids d'un mot plafonne à (k1 + 1)·idf : la 10ᵉ mention de « Python »
  n'apporte presque plus rien (TF-IDF, lui, croît linéairement).
- b : normalisation de longueur, de 0 (aucune) à 1 (complète). Une offre deux fois plus
  longue que la moyenne contient tout deux fois plus, par simple volume.
- idf = ln(1 + (N − df + 0.5) / (df + 0.5)) : la variante de Lucene, toujours positive (l'idf
  « classique » de Robertson devient négatif pour un mot présent dans plus de la moitié des
  documents).

Index inversé : pour chaque mot, les documents qui le contiennent et leurs comptes. Un mot
de la requête ne touche que ses documents : c'est ce qui rend BM25 rapide sur des millions
d'offres (ici 1 700, la question ne se pose pas encore).
"""

import math
from collections import Counter, defaultdict

import numpy as np

K1 = 1.2   # valeurs par défaut de Lucene / Elasticsearch
B = 0.75


class BM25:
    def __init__(self, docs: list[list[str]], k1: float = K1, b: float = B):
        self.k1, self.b = k1, b
        self.n = len(docs)
        self.lengths = np.array([len(d) for d in docs], dtype=float)
        self.avgdl = self.lengths.mean() if self.n else 0.0
        postings: dict[str, tuple[list[int], list[int]]] = defaultdict(lambda: ([], []))
        for i, doc in enumerate(docs):
            for word, count in Counter(doc).items():
                postings[word][0].append(i)
                postings[word][1].append(count)
        self.postings = {w: (np.array(ids), np.array(tfs, dtype=float))
                         for w, (ids, tfs) in postings.items()}

    def idf(self, word: str) -> float:
        df = len(self.postings[word][0]) if word in self.postings else 0
        return math.log(1 + (self.n - df + 0.5) / (df + 0.5))

    def scores(self, query: list[str]) -> np.ndarray:
        """Le score BM25 de chaque document pour la requête (un mot répété compte autant de
        fois : à dédoublonner en amont si on ne le veut pas)."""
        scores = np.zeros(self.n)
        # Dénominateur de longueur, calculé une fois pour tous les documents
        norm = self.k1 * (1 - self.b + self.b * self.lengths / (self.avgdl or 1))
        for word, q_count in Counter(query).items():
            if word not in self.postings:
                continue
            ids, tf = self.postings[word]
            scores[ids] += q_count * self.idf(word) * tf * (self.k1 + 1) / (tf + norm[ids])
        return scores
