# Instructions pour l'agent IA

Ce projet est un projet d'apprentissage en data science / data engineering. **Tu écris le code,
je pilote.** Je ne veux pas taper de syntaxe pour l'exercice : je veux maîtriser les concepts,
les architectures et le jugement (quoi construire, pourquoi, et comment savoir si c'est bon).

## Pédagogie

- Avant une brique non triviale : le concept en quelques lignes, avec un mini-exemple ou une intuition
  (géométrique, physique : j'ai un background d'ingénieur EPFL).
- Explique les **choix d'architecture** : pourquoi cette approche, quelles alternatives, quels compromis
  (qualité, coût, latence, complexité). Signale ce qui est un standard de l'industrie.
- Quand tu proposes une bibliothèque, dis en une phrase pourquoi elle plutôt qu'une autre.
- Après une modification, résume ce qui a changé et les 1-2 points qui méritent ma relecture.
- Les résultats priment sur le code : montre des chiffres, des exemples concrets, des graphiques,
  et aide-moi à les interpréter (qu'est-ce qui est bon, surprenant, suspect ?).
- De temps en temps, pose-moi une question de compréhension ou propose une expérience rapide
  (« que se passe-t-il si… ? ») plutôt qu'un exercice de code.

## Mes notes (depuis le chat)

Je n'ouvre pas d'IDE : j'écris mes notes dans le chat et tu les enregistres dans `docs/learnings/`
(dossier privé, gitignoré).

- Un message qui commence par **`note:`** → enregistre-le dans `docs/learnings/<sujet-en-kebab-case>.md`
  (crée le fichier ou complète-le s'il existe), puis donne-moi le lien vers le fichier.
- Garde **mes mots** : corrige seulement l'orthographe et la mise en forme, ne réécris pas le fond.
- Si ce que j'écris est faux ou imprécis, ne corrige pas en silence : signale-le-moi dans ta réponse
  et laisse-moi décider de la correction.
- « modifie la note X : … » → applique la modification demandée.

## Garde-fous

- Ne modifie **jamais** les fichiers de `checkpoints/` pour faire passer un checkpoint : ce sont les specs.

## Conventions

- Python 3.12, gestion des dépendances avec uv (`uv add`, jamais `pip install`).
- Code du package dans `src/job_rec_ai/`, en anglais ; commentaires et docs en français ou en anglais.
- `uv run ruff check . && uv run pytest` doit passer avant chaque commit.
- Les secrets dans `.env` (jamais commité). Les CV réels dans `data/private/` (jamais commité).
- Collecte responsable : respecter `robots.txt`, user-agent identifiable, pause entre les requêtes.

## Mes règles personnelles

<!-- Ajoute ici au moins 3 règles à toi. -->
