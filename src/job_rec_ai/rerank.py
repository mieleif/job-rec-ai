"""Reclassement de N candidats par un cross-encoder.

Un cross-encoder lit CV et offre ENSEMBLE : l'attention relie « 3 ans de Python » à
« Python senior exigé ». Plus juste qu'un cosinus entre deux vecteurs calculés séparément,
mais rien n'est pré-calculable : un passage du modèle par paire. D'où l'entonnoir : BM25 et
vecteurs réduisent 5 000 offres à ~60 candidats, le cross-encoder n'ordonne que ceux-là.
"""

from job_rec_ai.embeddings import Call, Client, Model

CANDIDATES = 60


def rerank(client: Client, model: Model, cv_text: str, candidates: list[str],
           texts: dict[str, str], max_tokens: int | None = None) -> tuple[list[str], Call]:
    """(candidats reclassés, coût). `max_tokens` : troncature de chaque offre côté serveur
    (None : pleine longueur, 4 096 tokens par défaut dans l'API)."""
    if not candidates:
        return [], Call()
    scores, call = client.rerank(model, cv_text, [texts[c] for c in candidates], max_tokens)
    order = sorted(range(len(candidates)), key=lambda i: -scores[i])
    return [candidates[i] for i in order], call
