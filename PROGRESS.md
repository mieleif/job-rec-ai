# Avancement

Le carnet de bord du projet : où on en est, ce qu'on a décidé et pourquoi, la suite.
Les tâches cochables restent dans [ROADMAP.md](ROADMAP.md) ; ce fichier ne les recopie pas.

_Dernière mise à jour : 2026-10-30_

## Où on en est

| Étape | Checkpoint | Ce qui reste |
|---|---|---|
| M0 · Setup | 9/9 (avec une note locale, voir « Contraintes ») | règles perso dans `CLAUDE.md`, Milestones GitHub, questions de contrôle |
| M1 · Collecte | 7/8 | `tests/fixtures/workday.json` (une vraie réponse d'ATS), vraie collecte : objectif 1 000 offres non vérifié, note HTTP, questions de contrôle |
| M2 · Pipeline | 7/7 | installer le timer sur le VPS, note ETL/ELT, questions de contrôle |
| M3 → M8 | pas commencé | |

Tests du projet : 71 réussis.

## Décisions

- **2026-10-30 · La base vit sur le VPS de Leif, la collecte nocturne aussi** (timer systemd,
  voir [`deploy/`](deploy/README.md)). Faire tourner la collecte sur GitHub Actions aurait
  obligé à transférer `jobs.duckdb` dans les deux sens chaque nuit et à confier une clé SSH à
  GitHub. GitHub Actions servira à la CI (M8).
- **2026-10-30 · Expiration : on alerte, on ne bloque pas.** La base s'aligne toujours sur la
  source. Une disparition massive (plus de la moitié des offres actives et au moins 5, ou une
  collecte vide) est signalée (`ALERTE`, statut `suspect`, commande `quality`). Si c'était une
  panne, les offres reviennent à la collecte suivante avec leur `first_seen` d'origine.
- **2026-10-30 · Un fichier brut par collecte** (`<ats>__<entreprise>__<hhmmss>.json.gz`) :
  deux collectes le même jour ne s'écrasent plus.
- **2026-10-22 · Dédoublonnage par URL ou par empreinte « entreprise + titre + lieu ».**
  Compromis accepté : deux vrais postes identiques au même endroit peuvent fusionner.

## Contraintes à connaître

- **Le réseau des sessions Claude cloud bloque les ATS** (`*.myworkdayjobs.com`,
  `api.smartrecruiters.com`). Toute collecte réelle, et la création des fixtures
  (`uv run job-rec-ai fixture <entreprise>`), se fait sur le VPS ou en local.
- **`docs/learnings/` est gitignoré** : les notes n'existent que sur la machine où elles ont
  été écrites. Une nouvelle session cloud repart d'un clone sans notes, et le test
  `test_premiere_note_de_savoir` y échoue. À décider : où garder les notes durablement.

## Prochaines étapes

1. Sur le VPS : installer la collecte nocturne ([deploy/README.md](deploy/README.md)),
   lancer `uv run job-rec-ai fixture Richemont`, committer la fixture.
2. Interpréter ensemble la première sortie de `uv run job-rec-ai quality`.
3. M3 : similarité cosinus (intuition géométrique, exemple 2D), puis TF-IDF from scratch et
   les métriques d'évaluation (precision@k, MRR, nDCG).
4. Finir M0 : règles perso dans `CLAUDE.md`, Milestones GitHub.

## Journal des sessions

- **2026-10-30** : revue et fusion du travail M1/M2 ; première note (venv) ; contrôles qualité
  (alerte d'expiration, commande `quality`, bronze par collecte) ; timer systemd pour le VPS ;
  création de ce fichier.
- **2026-10-22** : M1/M2 : connecteurs Workday et SmartRecruiters, modèle `Job`, DuckDB,
  upsert idempotent, diff de collectes, CLI (`crawl`, `search`, `stats`, `benchmark`…).
