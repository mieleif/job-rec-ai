# Intégration dans DoxAI (app.doxai.ch)

Ce que job-rec-ai fournit à DoxAI, et comment DoxAI s'en sert. Côté DoxAI, le travail se fait
dans le dépôt `mieleif/cv-app-web` et suit ses règles (`CLAUDE.md`, `memory-bank/`).

## Le service

| | |
|---|---|
| URL | `http://job-rec-ai:8000` (réseau Docker `n8n-stack_default`, pas d'URL publique) |
| Jeton | en-tête `Authorization: Bearer $JOB_REC_TOKEN` |
| Coût | aucun appel de modèle : pas de quota, pas de facturation (comme la compilation PDF) |
| Latence | quelques millisecondes (BM25 sur ~1 700 offres en mémoire) |
| Données | le texte envoyé n'est ni journalisé ni conservé |

### `POST /recommend`

```json
{ "cv_text": "texte du profil (1 à 50 000 caractères)", "k": 10, "cantons": ["GE", "VD"] }
```

`k` : 1 à 50 (10 par défaut). `cantons` : facultatif, filtre dur parmi GE, VD, FR, NE, VS, JU,
BE (Jura bernois et Bienne).

Réponse `200`, triée par score décroissant ; les offres sans aucun mot commun avec le profil
sont écartées (la liste peut donc être plus courte que `k`) :

```json
[{ "job_id": "https://…", "url": "https://…", "title": "Architecte logiciel junior - IA",
   "company": "Specitec", "canton": "GE", "family": "Data & IA", "seniority": "Junior",
   "workload_min": 100, "workload_max": 100, "posted_at": "2026-11-02",
   "publisher_type": "employeur", "score": 288.8 }]
```

Erreurs : `401` jeton absent ou faux, `422` entrée invalide, `503` base pas encore chargée.
`score` n'a pas d'échelle absolue (BM25) : il sert à ordonner, pas à afficher.

## Côté DoxAI (proposition)

1. **Connexion** : `JOB_REC_URL` + `JOB_REC_TOKEN` dans `cv-app.env`, lus côté serveur
   seulement (jamais dans le navigateur). Sans `JOB_REC_URL`, la fonctionnalité est masquée
   (comme le gateway : no-op quand non configuré), donc absente du staging.
2. **Route serveur** `GET /api/v2/recommendations` (`requireUser`) : charge le profil global,
   en tire un texte (expériences, projets, compétences, formation, profil professionnel ;
   jamais les coordonnées), appelle `/recommend`, renvoie la liste.
3. **Page** : les offres recommandées, en cartes Atelier ; le bouton « Ajouter à mes
   candidatures » réutilise le flux existant `POST /api/v2/opportunities { url, company,
   role }` (déduplication par URL déjà faite par `createOrGetOpportunity`), puis mène au
   dossier, où l'analyse d'adéquation existante prend le relais.

Mesures connues (jeu d'évaluation de Leif, 38 offres notées) : nDCG@10 = 0,779. C'est une
baseline lexicale : « IA » et « AI » ne se rejoignent pas encore (embeddings en M4).
