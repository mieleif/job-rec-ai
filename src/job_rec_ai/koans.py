"""Les briques de M3, écrites à la main pour les comprendre (sans scikit-learn).

Contrat : checkpoints/test_m3_baseline.py.
"""

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
