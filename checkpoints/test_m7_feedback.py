"""Checkpoint M7 : feedback et recommandation.

Contrat attendu (src/job_rec_ai/recsys.py) :
- rocchio_update(profile, liked, disliked, alpha=1.0, beta=0.75, gamma=0.15)
    nouveau = alpha·profil + beta·moyenne(liked) − gamma·moyenne(disliked)
    (un terme est omis si sa liste est vide), puis normalisé (norme L2 = 1).
    ValueError si le vecteur résultant est nul.
- interleave_exploration(exploit, explore, every) -> list
    insère un élément d'exploration à chaque position multiple de `every`
    (positions comptées à partir de 1) ; ignore les éléments d'exploration déjà présents
    dans exploit ; quand l'exploration est épuisée, continue avec exploit ;
    ValueError si every < 2.
"""

import pytest


def test_rocchio_mise_a_jour(need):
    """Déplacer le profil vers les likes et l'éloigner des dislikes, puis normaliser."""
    rocchio = need("job_rec_ai.recsys", "rocchio_update")
    out = rocchio([1, 0], liked=[[0, 1]], disliked=[[1, 0]], alpha=1, beta=1, gamma=0.5)
    norm = (0.5**2 + 1**2) ** 0.5
    assert list(out) == pytest.approx([0.5 / norm, 1 / norm])


def test_rocchio_moyenne_des_likes(need):
    """Utiliser la MOYENNE des likes, pas leur somme."""
    rocchio = need("job_rec_ai.recsys", "rocchio_update")
    out = rocchio([0, 0, 1], liked=[[1, 0, 0], [0, 1, 0]], disliked=[], alpha=1, beta=2, gamma=0)
    assert list(out) == pytest.approx([1 / 3 ** 0.5] * 3)


def test_rocchio_sans_feedback(need):
    """Sans aucun feedback, renvoyer simplement le profil normalisé."""
    rocchio = need("job_rec_ai.recsys", "rocchio_update")
    assert list(rocchio([3, 4], liked=[], disliked=[])) == pytest.approx([0.6, 0.8])


def test_rocchio_vecteur_nul(need):
    """Lever une ValueError si le profil résultant est nul."""
    rocchio = need("job_rec_ai.recsys", "rocchio_update")
    with pytest.raises(ValueError):
        rocchio([1, 0], liked=[], disliked=[[1, 0]], alpha=1, gamma=1)


def test_exploration_entrelacee(need):
    """Glisser une offre « découverte » toutes les `every` positions."""
    interleave = need("job_rec_ai.recsys", "interleave_exploration")
    exploit = [f"e{i}" for i in range(1, 9)]
    out = interleave(exploit, ["x1", "x2"], every=4)
    assert out == ["e1", "e2", "e3", "x1", "e4", "e5", "e6", "x2", "e7", "e8"]


def test_exploration_sans_doublon(need):
    """Ignorer une offre d'exploration déjà présente dans les recommandations."""
    interleave = need("job_rec_ai.recsys", "interleave_exploration")
    out = interleave(["e1", "e2", "e3", "e4"], ["e2", "x1"], every=3)
    assert out == ["e1", "e2", "x1", "e3", "e4"]
    with pytest.raises(ValueError):
        interleave(["e1"], ["x1"], every=1)
