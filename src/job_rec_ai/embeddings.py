"""Embeddings : un texte → un vecteur dense de 384 nombres qui encode son SENS.

Un réseau de neurones (un transformer) a été entraîné sur des millions de paires de textes
« qui vont ensemble » (question / réponse, titre / article, phrase / traduction) à placer
leurs vecteurs proches, et les autres loin. Résultat : « IA », « AI » et « intelligence
artificielle » tombent au même endroit de l'espace, même sans mot commun. BM25 ne voit que
des mots identiques.

Modèle : intfloat/multilingual-e5-small (118 M paramètres, 384 dimensions, ~100 langues,
512 tokens au plus). Petit : il tourne sur CPU. Il distingue les deux côtés d'une recherche
par un préfixe, « query: » (le CV) et « passage: » (l'offre) : l'asymétrie que BM25 a par
construction. Le texte au-delà de 512 tokens est tronqué (voir le chunking).

Les vecteurs des offres sont mis en cache (data/embeddings/) : une offre n'est calculée
qu'une fois, tant que son texte ne change pas.
"""

import hashlib
from functools import cache
from pathlib import Path

import numpy as np

MODEL = "intfloat/multilingual-e5-small"
CACHE_DIR = Path("data/embeddings")
BATCH = 32


@cache
def _model():
    from sentence_transformers import SentenceTransformer  # lourd (torch) : à la demande
    return SentenceTransformer(MODEL, device="cpu")


def encode(texts: list[str], kind: str) -> np.ndarray:
    """Vecteurs normalisés (norme 1) : le produit scalaire EST alors le cosinus."""
    prefix = {"query": "query: ", "passage": "passage: "}[kind]
    return _model().encode([prefix + t for t in texts], batch_size=BATCH,
                           normalize_embeddings=True, convert_to_numpy=True)


def _key(text: str) -> str:
    return hashlib.sha1(f"{MODEL}\n{text}".encode()).hexdigest()


def passage_matrix(texts: list[str], cache_dir: Path | None = None) -> np.ndarray:
    """Un vecteur par texte (lignes dans l'ordre de `texts`), calculé seulement s'il n'est pas
    déjà en cache. Clé = empreinte du modèle et du texte."""
    path = (cache_dir or CACHE_DIR) / f"{MODEL.split('/')[-1]}.npz"
    known: dict[str, np.ndarray] = {}
    if path.exists():
        with np.load(path) as data:
            known = dict(zip(data["keys"], data["vectors"]))
    keys = [_key(t) for t in texts]
    missing = [i for i, k in enumerate(keys) if k not in known]
    if missing:
        vectors = encode([texts[i] for i in missing], "passage")
        known.update({keys[i]: v for i, v in zip(missing, vectors)})
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez(path, keys=np.array(list(known)), vectors=np.stack(list(known.values())))
    return np.stack([known[k] for k in keys])
