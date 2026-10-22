"""Checkpoint M4 : embeddings et recherche.

Contrat attendu :
- job_rec_ai.search.rrf_fuse(rankings: list[list[str]], k: int = 60) -> list[str]
    score(d) = Σ 1 / (k + rang), rang commençant à 1 ; tri par score décroissant.
- job_rec_ai.text.chunk_text(text, max_words, overlap) -> list[str]
    découpe en mots ; chaque chunk ≤ max_words ; deux chunks consécutifs partagent
    exactement `overlap` mots ; pas de dernier chunk redondant ; texte vide → [] ;
    ValueError si overlap >= max_words.
"""

import pytest


def test_rrf_fusionne_par_rang(need):
    """Fusionner deux classements par Reciprocal Rank Fusion."""
    rrf = need("job_rec_ai.search", "rrf_fuse")
    assert rrf([["a", "b", "c"], ["b", "c", "a"]]) == ["b", "a", "c"]


def test_rrf_garde_tous_les_documents(need):
    """Garder un document présent dans un seul des classements."""
    rrf = need("job_rec_ai.search", "rrf_fuse")
    out = rrf([["a", "b"], ["c"]])
    assert set(out) == {"a", "b", "c"}
    assert out.index("a") < out.index("b")


def test_rrf_parametre_k(need):
    """Respecter le paramètre k (un k petit avantage fortement le 1er rang)."""
    rrf = need("job_rec_ai.search", "rrf_fuse")
    rankings = [["x", "b", "c", "d"], ["y", "b", "z", "x"]]
    assert rrf(rankings, k=60)[0] == "b"  # régulier partout
    assert rrf(rankings, k=1)[0] == "x"   # un 1er rang écrase tout


def test_chunk_taille_et_chevauchement(need):
    """Découper en chunks de max_words mots, avec exactement `overlap` mots en commun."""
    chunk = need("job_rec_ai.text", "chunk_text")
    text = " ".join(f"w{i}" for i in range(10))
    out = chunk(text, max_words=4, overlap=1)
    assert out == ["w0 w1 w2 w3", "w3 w4 w5 w6", "w6 w7 w8 w9"]


def test_chunk_cas_limites(need):
    """Gérer les cas limites : texte court, texte vide, overlap invalide."""
    chunk = need("job_rec_ai.text", "chunk_text")
    assert chunk("un deux trois", max_words=10, overlap=2) == ["un deux trois"]
    assert chunk("", max_words=10, overlap=2) == []
    with pytest.raises(ValueError):
        chunk("a b c", max_words=3, overlap=3)
