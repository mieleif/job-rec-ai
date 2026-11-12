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
[{ "job_id": "https://…", "id": "3f9c0a7e12b4d5c6", "url": "https://…",
   "title": "Architecte logiciel junior - IA",
   "company": "Specitec", "company_domain": "specitec.com", "location": "Genève", "canton": "GE",
   "family": "Data & IA", "seniority": "Junior",
   "workload_min": 100, "workload_max": 100, "posted_at": "2026-11-02",
   "publisher_type": "employeur", "snippet": "Au sein de notre équipe…", "score": 288.8 }]
```

`location` et `snippet` (ajoutés le 12.11.2026) : les mêmes que sur `GET /jobs`, pour le lieu et
l'extrait des cartes « Offres recommandées ».

`id` (ajouté le 07.11.2026, rien d'autre n'a changé) : l'identifiant de l'offre pour les routes
`/jobs` ci-dessous, donc pour lier une recommandation à sa page publique.
`company_domain` (ajouté le 07.11.2026, voir « Logo de l'employeur » plus bas) : présent sur
`/recommend` comme sur les trois routes `/jobs`.

`GET /status` (même jeton) : `{"offers": 1706, "loaded_at": "…"}`, pour vérifier que l'index
est chargé. `GET /health` répond sans jeton.

Erreurs : `401` jeton absent ou faux, `422` entrée invalide, `503` base pas encore chargée.
`score` n'a pas d'échelle absolue (BM25) : il sert à ordonner, pas à afficher.

## Pages publiques d'offres : les routes `/jobs`

Pour la liste cherchable (`/fr/emplois`) et la page de chaque offre. Même jeton, mêmes erreurs
`401` / `422` / `503`. Le service ne traduit rien : la traduction à la demande est faite par
DoxAI, à partir du Markdown.

**Identifiant** : `id` = les 16 premiers caractères hexadécimaux du SHA-256 de l'URL de
l'offre (`[0-9a-f]{16}`). Stable d'une collecte à l'autre tant que l'URL ne change pas ; une
offre expirée disparaît des routes (404). Recherche par `id` en O(1) (dictionnaire en mémoire).

### `GET /jobs`

| Paramètre | |
|---|---|
| `q` | recherche plein texte BM25 sur titre + entreprise + description ; seules les offres qui contiennent au moins un mot de la recherche sont gardées |
| `cantons` | `GE,VD` (virgules, casse indifférente) |
| `workload_min`, `workload_max` | 0 à 100 ; une offre est gardée si sa plage de taux **recouvre** la plage demandée ; sans taux affiché, elle compte pour 100 % ; `workload_min > workload_max` → `422` |
| `posted_within_days` | publiée depuis au plus n jours (0 à 3650) ; sans date de publication (Prospective), la date de première collecte |
| `page`, `per_page` | `page` ≥ 1 ; `per_page` 1 à 50 (20 par défaut) |
| `sort` | `relevance` (défaut si `q`) ou `recent` (défaut sinon : `posted_at` décroissant, sans date à la fin) |

```json
{ "total": 412, "page": 1, "per_page": 20, "companies": 41,
  "jobs": [JobSummary, …],
  "facets": { "cantons": { "GE": 120, "VD": 98, "FR": 30 } } }
```

`facets.cantons` compte les offres qui passent **tous les filtres sauf `cantons`** (pour afficher
« Vaud (98) » même quand seul Genève est coché), triées par nombre décroissant.
`companies` est le nombre d'employeurs distincts parmi les `total` résultats (tous les filtres
appliqués), pour « 412 offres de 41 entreprises ».

`JobSummary` :

```json
{ "id": "3f9c0a7e12b4d5c6", "url": "https://…", "title": "Data Engineer", "company": "Acme",
  "company_domain": "acme.ch", "location": "Genève", "canton": "GE", "workload_min": 80, "workload_max": 100,
  "posted_at": "2026-11-02", "language": "fr", "employment_type": "Full time",
  "family": "Data & IA", "snippet": "Python, SQL, dbt et Airflow pour la plateforme…" }
```

`canton`, `workload_*`, `posted_at`, `employment_type`, `family`, `company_domain` peuvent
être `null`.
`language` : `fr`, `de`, `en`, `it` ou `null` (indéterminée : texte trop court). `snippet` :
au plus 240 caractères de texte brut, coupé sur une fin de mot avec « … ».

### `GET /jobs/{id}`

`JobSummary` plus :

```json
{ "description_markdown": "### Vos missions\n\n- Concevoir…\n- Maintenir…",
  "description_text": "Vos missions Concevoir… Maintenir…",
  "category": null, "seniority": "Confirmé·e", "source": "workday" }
```

`404 {"detail": "not_found"}` si l'offre est inconnue ou expirée.

`description_markdown` garde la structure de l'annonce de l'ATS : titres `##` / `###` (jamais
`#`), paragraphes, listes à puces et numérotées (un seul niveau), gras et italique, liens
`[texte](url)` vers http(s) seulement. Jamais d'image, de script, de style, d'iframe ni de
HTML brut ; les caractères spéciaux du texte sont échappés (`\*`, `\<`…). Les tableaux sont
aplatis en listes. Sans HTML d'origine (Cornerstone, JSON-LD de l'État de Genève), des
paragraphes tirés du texte brut. À rendre avec un moteur CommonMark/GFM **sans HTML brut
autorisé** (react-markdown par défaut).

`description_text` : le texte brut sur une ligne, celui que lit le moteur de recommandation.

### `GET /jobs/{id}/similar?k=4`

`k` : 1 à 12 (4 par défaut). `[JobSummary]`, les offres les plus proches de celle-ci (BM25 sur
son titre et sa description), elle-même exclue, sans offre à score nul (la liste peut être plus
courte que `k`). `404` si l'offre est inconnue.

## Logo de l'employeur : `company_domain`

Ajouté le 07.11.2026, purement additif (aucun champ renommé ni retiré, classement de
`/recommend` inchangé). Chaque offre de `GET /jobs`, `GET /jobs/{id}`, `GET /jobs/{id}/similar`
et `POST /recommend` porte `company_domain` : le domaine nu de l'employeur, en minuscules, sans
schéma, chemin ni `www.` (`vitol.com`, `coop.ch`, `home.cern`), ou `null` s'il est inconnu.

DoxAI en tire le logo : `https://img.logo.dev/<company_domain>?token=<clé publiable>`, et un
favicon en repli ; sans domaine, pas de logo (initiale, par exemple). La clé publiable est
celle de DoxAI ; la clé **secrète** de logo.dev ne sert qu'ici, côté serveur, et jamais dans
l'API.

D'où vient le domaine, par priorité :

1. `data/company_domains.csv` (`company,domain,reason`) : corrections à la main ; un domaine
   vide y force `null` (pas de logo plutôt qu'un faux) ;
2. la colonne `domain` de `data/companies.csv` : remplie pour les 65 sources collectées,
   d'après leur propre site carrière ou tenant d'ATS ;
3. sinon la recherche de marques de logo.dev (`GET https://api.logo.dev/v2/search?q=<nom>`,
   `LOGO_DEV_SECRET_KEY`) : un candidat n'est retenu que si son nom, normalisé (accents,
   casse, « SA », « AG », « Sàrl », « GmbH », « Ltd »… ignorés), est exactement celui de
   l'entreprise ; plusieurs domaines pour ce nom : le seul en `.ch`, sinon `null`.

Le résultat est mis en cache en base (table `company_domains`, un appel par entreprise ; un
`null` est revérifié après 30 jours). La résolution tourne à la fin de la collecte nocturne et
par `job-rec-ai resolve-domains`, jamais pendant une requête : l'API lit le cache, et le
recharge comme le reste de la base (au plus 5 minutes après).

## Côté DoxAI (proposition)

1. **Connexion** : `JOB_REC_URL` + `JOB_REC_TOKEN`, lus côté serveur seulement (jamais dans
   le navigateur). Sans `JOB_REC_URL`, la fonctionnalité est masquée (comme le gateway : no-op
   quand non configuré). Consigne de Leif : les changements d'interface passent d'abord par le
   staging (`/opt/n8n-stack/staging/staging.env`) ; la prod (`cv-app.env`) reste sans ces
   variables jusqu'à sa décision. Commandes : [deploy/README.md](../deploy/README.md).
2. **Route serveur** `GET /api/v2/recommendations` (`requireUser`) : charge le profil global,
   en tire un texte (expériences, projets, compétences, formation, profil professionnel ;
   jamais les coordonnées), appelle `/recommend`, renvoie la liste.
3. **Page** : les offres recommandées, en cartes Atelier ; le bouton « Ajouter à mes
   candidatures » réutilise le flux existant `POST /api/v2/opportunities { url, company,
   role }` (déduplication par URL déjà faite par `createOrGetOpportunity`), puis mène au
   dossier, où l'analyse d'adéquation existante prend le relais.

Mesures connues (jeu d'évaluation de Leif, 38 offres notées) : nDCG@10 = 0,779. C'est une
baseline lexicale : « IA » et « AI » ne se rejoignent pas encore (embeddings en M4).
