# job-rec-ai

**Un moteur open-source de recommandation d'emplois à partir d'un CV.**

Collecte d'offres réelles (Genève d'abord, puis toute la Suisse), embeddings multilingues FR/EN,
recherche sémantique, re-ranking et apprentissage à partir de swipes : un « Tinder des jobs »
construit étape par étape, comme projet d'apprentissage en data engineering et data science.

## Avancement

Voir **[ROADMAP.md](ROADMAP.md)** : 9 étapes, chacune validée par des tests d'acceptation
(`checkpoints/`).

| Étape | Statut |
|---|---|
| M0 · Setup | 🚧 en cours |
| M1 · Collecte | ⏳ |
| M2 · Pipeline | ⏳ |
| M3 · Baseline et évaluation | ⏳ |
| M4 · Embeddings et recherche sémantique | ⏳ |
| M5 · Enrichissement par LLM | ⏳ |
| M6 · Re-ranking | ⏳ |
| M7 · Feedback et swipe | ⏳ |
| M8 · Production | ⏳ |

## Structure

```
src/job_rec_ai/     le moteur (créé à l'étape M0)
checkpoints/        tests d'acceptation de chaque étape de la roadmap
docs/learnings/     notes personnelles (privées, non versionnées) + modèle
```

## Licence

MIT (à confirmer)
