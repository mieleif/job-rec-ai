# Roadmap

Neuf étapes, de la collecte des offres jusqu'à une API en production. Chaque étape a :

- **🎯 Objectif** : un résultat visible et démontrable, pas une liste de concepts ;
- **Tâches** : petites et cochables. ⚡ = moins de 30 min, pour les jours où l'énergie manque ;
- **🖼️ Livrable** : quelque chose à montrer (graphique, tableau, démo) à mettre dans le README ;
- **✅ Checkpoint** : l'étape est terminée quand les tests de `checkpoints/` passent
  **et** que je sais répondre aux questions de contrôle avec mes mots (réponses notées dans `docs/learnings/`, privé et gitignoré : écrire `note: …` dans le chat).

Lancer un checkpoint : `uv run pytest checkpoints/test_m1_collecte.py -v`

---

## M0 · Setup

🎯 Un repo GitHub public, propre, prêt à accueillir du code.

- [x] ⚡ Installer uv, puis Python 3.12 (`uv python install 3.12`)
- [x] Initialiser le projet : `uv init --package --name job-rec-ai --python 3.12` (crée le package `src/job_rec_ai/`)
- [x] ⚡ Outils de dev : `uv add --dev ruff pytest`, section `[tool.ruff]`, et `testpaths = ["tests"]` dans `[tool.pytest.ini_options]` (les checkpoints se lancent à part)
- [x] ⚡ Exposer `job_rec_ai.__version__`
- [ ] ⚡ Premier commit + repo GitHub public (vérifier `.gitignore` avant)
- [ ] ⚡ Ajouter mes propres règles dans `CLAUDE.md`
- [ ] Créer les Milestones GitHub M0 à M8 et une issue par tâche (barres de progression natives)
- [ ] Note : venv, lockfile, dépendances de dev

🖼️ Le repo en ligne, avec le tableau des Milestones qui se remplit.

✅ `checkpoints/test_m0_setup.py`
- Pourquoi un environnement virtuel ? Pourquoi versionner `uv.lock` ?
- Quelle différence entre une dépendance et une dépendance de dev ?
- Quelles règles ai-je données à l'agent IA, et pourquoi ?

---

## M1 · Collecte

🎯 Plus de 1 000 vraies offres genevoises dans une table propre.

- [ ] Note : HTTP, codes de statut, JSON, `robots.txt`, rate limiting
- [ ] Lister 50+ employeurs genevois dans `data/companies.csv` (nom, secteur, URL carrière)
- [ ] Identifier l'ATS de chacun (Greenhouse, Lever, SmartRecruiters, Workday, Personio…)
- [x] Modèle `Job` avec pydantic
- [ ] ⚡ Sauvegarder une vraie réponse JSON d'ATS dans `tests/fixtures/`
- [x] Premier connecteur ATS : `fetch()` + `parse()` → `list[Job]`
- [x] Deuxième connecteur + `REGISTRY`
- [x] Dédoublonnage des offres
- [ ] Stockage en base (DuckDB pour démarrer) et cap des 1 000 offres

🖼️ Graphique « Top 20 des employeurs qui recrutent à Genève » + répartition des langues.

✅ `checkpoints/test_m1_collecte.py`
- Que signifie un code 429, et comment mon crawler le gère-t-il ?
- Pourquoi un connecteur par ATS plutôt qu'un scraper par site ?
- Quel est le parcours d'une offre, de l'ATS jusqu'à ma base, et où peut-elle se corrompre ?

---

## M2 · Pipeline

🎯 La collecte tourne chaque nuit, toute seule, sans doublons.

- [ ] Note : ETL vs ELT, idempotence, données brutes (bronze / silver / gold)
- [x] `clean_html` : HTML → texte propre
- [x] ⚡ `detect_language` : fr / en / other
- [x] Diff entre deux collectes : nouvelles, modifiées, expirées
- [x] Upsert idempotent (relancer = zéro doublon)
- [x] Commande `uv run job-rec-ai crawl`
- [x] Contrôles qualité (champs vides, anomalies)
- [ ] Planification nocturne sur le VPS (timer systemd, voir `deploy/`)

🖼️ Notebook « Le marché de l'emploi genevois en 5 graphiques ».

✅ `checkpoints/test_m2_pipeline.py`
- Qu'est-ce qu'une opération idempotente, et pourquoi est-ce vital ici ?
- Le crawler plante à 60 % : que se passe-t-il au prochain lancement ?
- Pourquoi garder les données brutes en plus des données nettoyées ?

---

## M3 · Baseline et évaluation

🎯 Une première recommandation pour mon CV, avec un score chiffré.

- [ ] Similarité cosinus : intuition géométrique, calcul sur un exemple 2D, puis implémentation numpy (`koans.py`)
- [ ] TF-IDF from scratch, puis comparaison avec scikit-learn : pourquoi les scores diffèrent-ils ?
- [ ] ⚡ Extraire le texte de mon CV (hors du repo : `data/private/`)
- [ ] Moteur BM25 : CV → offres classées
- [ ] Jeu d'évaluation : 4-5 CV anonymisés × ~20 offres notées 0/1/2
- [ ] precision@k, MRR, nDCG@k
- [ ] Commande `uv run job-rec-ai eval`
- [ ] Note : pourquoi mesurer avant d'optimiser

🖼️ Mon premier top 10 + le tableau de scores de la baseline.

✅ `checkpoints/test_m3_baseline.py`
- Expliquer la similarité cosinus géométriquement. Pourquoi pas la distance euclidienne ?
- Pourquoi l'IDF réduit-il le poids des mots fréquents ?
- Quel est le risque de toujours ajuster le modèle sur les mêmes CV d'évaluation ?

---

## M4 · Embeddings et recherche sémantique

🎯 Une recherche sémantique qui bat BM25, preuve chiffrée à l'appui.

- [ ] Note : qu'est-ce qu'un embedding ? (expérience FR/EN à l'appui)
- [ ] Embeddings avec un modèle multilingue local (sentence-transformers)
- [ ] Chunking avec chevauchement
- [ ] Base vectorielle (pgvector ou DuckDB VSS) + index HNSW
- [ ] Même chose via une API : comparaison qualité / coût / latence
- [ ] Recherche hybride BM25 + vecteurs (Reciprocal Rank Fusion)

🖼️ Tableau BM25 vs embeddings vs hybride + carte UMAP interactive des offres.

✅ `checkpoints/test_m4_embeddings.py`
- Expliquer un embedding à quelqu'un qui n'a jamais fait de ML.
- Pourquoi la recherche hybride bat-elle souvent les vecteurs seuls ?
- Qu'échange-t-on avec un index HNSW ?

---

## M5 · Enrichissement par LLM

🎯 Offres et CV structurés, recommandations expliquées.

- [ ] Schéma `JobFacts` (compétences, séniorité, télétravail, langues, salaire)
- [ ] Extraction structurée par LLM sur 50 offres
- [ ] Vérifier 20 extractions à la main : taux d'erreur par champ
- [ ] ⚡ Suivi des coûts + cache des réponses
- [ ] Même extraction pour les CV
- [ ] Filtres (langue, télétravail, séniorité)
- [ ] « Pourquoi ce job te correspond » en 3 puces
- [ ] Note : hallucinations, température, structured output

🖼️ Top 30 des compétences les plus demandées à Genève.

✅ `checkpoints/test_m5_llm.py`
- Pourquoi un structured output plutôt que « réponds en JSON » ?
- Comment mesurer la qualité d'une extraction LLM ?
- Quand un LLM est-il le bon outil, et quand une règle simple suffit-elle ?

---

## M6 · Re-ranking

🎯 Un top 10 visiblement meilleur grâce au classement en deux étapes.

- [ ] Note : bi-encoder vs cross-encoder
- [ ] Récupérer 100 candidats → reclasser les 10 meilleurs
- [ ] Re-ranker cross-encoder multilingue
- [ ] Variante LLM comme re-ranker (attention au biais de position)
- [ ] ⚡ Score de fraîcheur (décroissance exponentielle, demi-vie)
- [ ] Score combiné (similarité + re-ranker + fraîcheur)
- [ ] ⚡ Mesurer la latence de chaque étape

🖼️ Leaderboard nDCG@10 de toutes les méthodes depuis M3.

✅ `checkpoints/test_m6_reranking.py`
- Pourquoi ne pas utiliser le cross-encoder sur toutes les offres ?
- Quelle étape a apporté le plus gros gain, et laquelle ne valait pas son coût ?
- Comment ai-je choisi les poids du score combiné ? Quelles limites ?

---

## M7 · Feedback et swipe

🎯 Une app où je swipe des offres et où les recommandations s'améliorent en direct.

- [ ] App de swipe (Streamlit) 👍 / 👎
- [ ] Log des interactions (utilisateur, offre, action, horodatage, position affichée)
- [ ] Mise à jour du profil par Rocchio
- [ ] ⚡ Cold start : partir du CV, puis basculer vers les swipes
- [ ] Exploration : glisser régulièrement une offre « découverte »
- [ ] Faire tester par 3 amis
- [ ] Learning-to-rank avec LightGBM
- [ ] Note : feedback implicite vs explicite, biais

🖼️ Courbe « qualité des recommandations en fonction du nombre de swipes ».

✅ `checkpoints/test_m7_feedback.py`
- Qu'est-ce que le cold start et comment le gère-t-on ?
- Pourquoi injecter de l'exploration ? Comment mesurer l'effet bulle ?
- Qu'ont révélé les tests des amis que le jeu d'évaluation ne montrait pas ?

---

## M8 · Production

🎯 Une API en ligne et une démo publique.

- [ ] API FastAPI : `GET /health`, `POST /recommend`
- [ ] CI GitHub Actions : ruff + pytest à chaque push
- [ ] Dockerfile
- [ ] Déploiement (Hugging Face Spaces, Fly.io, Render…)
- [ ] Logs structurés + métriques de base
- [ ] README vitrine : GIF de démo, architecture, résultats
- [ ] Article ou post sur ce que j'ai appris

🖼️ Un lien de démo à mettre sur le CV.

✅ `checkpoints/test_m8_production.py`
- Dessiner l'architecture complète, de la collecte nocturne au swipe.
- Que casserait en premier avec 1 000 utilisateurs ?
- Qu'est-ce que je referais différemment ?
