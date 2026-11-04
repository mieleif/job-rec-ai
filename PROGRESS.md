# Avancement

Le carnet de bord du projet : où on en est, ce qu'on a décidé et pourquoi, la suite.
Les tâches cochables restent dans [ROADMAP.md](ROADMAP.md) ; ce fichier ne les recopie pas.

_Dernière mise à jour : 2026-11-04_

## Où on en est

| Étape | Checkpoint | Ce qui reste |
|---|---|---|
| M0 · Setup | 9/9 (avec une note locale, voir « Contraintes ») | règles perso dans `CLAUDE.md`, Milestones GitHub, questions de contrôle |
| M1 · Collecte | **8/8** (fixtures réelles pour les 10 connecteurs) | **1 002 offres réelles** (608 GE, 394 VD, 42 employeurs ; repère : jobup.ch ~2 000 pour Genève). Restent : note HTTP, questions de contrôle |
| M2 · Pipeline | 7/7 | installer le timer sur le VPS, note ETL/ELT, questions de contrôle |
| M3 → M8 | pas commencé | |

Tests du projet : 128 réussis.

## Décisions

- **2026-11-04 · Filtrer côté serveur sur le pays quand l'ATS le permet.** Workday (facette
  `locationCountry`, à défaut `locations` avec les villes que reconnaît `geo`), Oracle
  (`location=Switzerland`) et Phenom (`qcountry`) restreignent la recherche à la Suisse ; le
  filtre de lieu GE/VD reste appliqué offre par offre. PwC : 3 800 offres dans le monde pour
  9 chez nous, JPMorgan : 7 100 pour 11. Vérifié : mêmes chiffres qu'avec le parcours complet,
  offres multi-sites comprises (la facette pays couvre tous les lieux d'une offre : Logitech,
  Alcon). Une facette sans valeur reconnue (pays traduit « Suisse », sites codés) ne prouve
  pas l'absence d'offre : on retombe alors sur le parcours complet (revue de la PR #6).
- **2026-11-04 · Quatre ATS de plus, et un site maison.** Oracle Recruiting Cloud (UBP, OIM,
  JPMorgan), Taleo (OMS, OMPI), Phenom (PMI, P&G, Givaudan), careers.un.org (Secrétariat de
  l'ONU). Le CERN a son propre connecteur (`cern`) : exception à « un connecteur par ATS »,
  justifiée par son volume ; les classes CSS d'un thème WordPress sont fragiles, d'où une
  erreur explicite si plus aucun article n'est lisible.
- **2026-11-04 · SuccessFactors : commune et canton en microdonnées avant l'URL.** Coop sépare
  `addressLocality` (« Aclens », inconnue de `geo`) et `addressRegion` (« Vaud ») : 127 → 209
  offres. Titre de repli `og:title` (l'UIT n'a pas d'`itemprop="title"`).
- **2026-11-03 · Sites maison : un connecteur JSON-LD générique** plutôt qu'un scraper par site.
  L'État de Genève publie ses offres sur ge.ch, chaque annonce balisée en JSON-LD JobPosting :
  le connecteur `jsonld` lit la page de liste (liens un niveau sous le board, `rel="next"`),
  puis le JSON-LD de chaque annonce, et archive ce JSON-LD. Pas de filtre de lieu (l'employeur
  est choisi parce qu'il est local ; ses lieux sont des adresses sans ville).
- **2026-11-03 · Canton de repli : celui de l'employeur**, dans la vue gold `jobs_view`
  (`coalesce`). La table `jobs` garde le canton déduit du lieu seul (25 offres sans canton) :
  l'information manquante reste visible en silver.
- **2026-11-03 · Le client HTTP réessaie aussi sur les pannes réseau** (connexion qui
  n'aboutit pas, timeout), avec le même backoff : ge.ch a été injoignable par intermittence.
- **2026-11-03 · SuccessFactors : le sitemap, puis les microdonnées.** Chaque employeur a son
  site (jobs.sicpa.com, careers.epfl.ch…), d'une génération ancienne (HTML) ou récente
  (JavaScript nourri par `/services/`, interdit par robots.txt). Point commun autorisé :
  `sitemap.xml` liste toutes les annonces, et chaque annonce porte des microdonnées schema.org
  (module partagé `schema_org.py`, aussi utilisé par SmartRecruiters). Génération récente : le
  lieu se lit dans l'URL (`/job/<Lieu>-<Titre>/<id>/`, ce qui précède le titre), la date dans
  `<lastmod>`. Au-delà de 300 annonces (Nestlé : 2 100), pré-filtre sur l'URL avant de
  télécharger. On n'archive que les balises de microdonnées (fixture : 162 Ko → 19 Ko).
- **2026-11-03 · SmartRecruiters : le site public, pas l'API.** Le connecteur lit
  `careers.smartrecruiters.com/<id>` (liste HTML paginée par `api/groups?page=N`) puis
  `jobs.smartrecruiters.com/<id>/<offre>` (annonce balisée en schema.org JobPosting, parsée avec
  BeautifulSoup). Ces hôtes ne publient pas de robots.txt (404) : tout y est permis par
  convention (RFC 9309). Seul `<main>` est archivé en bronze. Piège rencontré : chaque
  employeur groupe sa liste par service (HUG, lieu sur l'offre) ou par lieu (Vitol, lieu dans
  l'en-tête du groupe) ; on lit les deux. CERN redirige vers son propre site : marqué `maison`.
- **2026-11-02 · SmartRecruiters : contexte.** Son `robots.txt` interdit l'API à tous les robots
  sauf LinkedIn (`User-agent: * / Disallow: /`) : le `PoliteClient` refuse donc toute requête.
  Aucune fixture réelle ne peut être créée légitimement, d'où le checkpoint M1 à 7/8.
  Enjeu mesuré le 2026-11-03 (un relevé ponctuel, à la demande de Leif, robots.txt ignoré :
  une requête par employeur, rien de stocké) : 7 employeurs, 586 offres dont **au moins 121 en
  GE/VD** (HUG 47, CERN 33, Swissquote 28, Vitol 8, Nexthink 5 ; LDC 0 sur les 100 premières de
  365). Piste légitime : le site public `careers.smartrecruiters.com/<entreprise>` est, lui,
  autorisé par son robots.txt (HTML à parser au lieu de JSON).
- **2026-11-02 · Connecteur Greenhouse** (Proton) : une seule requête rapporte tout le board,
  descriptions comprises, et la langue déclarée de l'annonce.
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
- **2026-10-30 · Notes d'apprentissage dans Notion** plutôt que dans git : privées, durables,
  lisibles hors IDE ; le dépôt public n'en contient que le modèle.
- **2026-10-22 · Dédoublonnage par URL ou par empreinte « entreprise + titre + lieu ».**
  Compromis accepté : deux vrais postes identiques au même endroit peuvent fusionner.

## Contraintes à connaître

- **Coop : des annonces sans description** (titre, taux, référence seulement : c'est ce que
  publie Coop). 209 offres sur 1 002, presque toutes classées « Autre » et en langue « other »
  (texte trop court pour la détection). À pondérer, voire à écarter, pour la recommandation.
- **Sans connecteur possible pour l'instant** : UNIGE (contrôle anti-robot « Vérification de
  sécurité »), TPG (403), Edmond de Rothschild (offres suisses sans ville), OMC (lieu « CWR »),
  Ferring (pas d'offre suisse sur son board Workday), API WordPress du CERN (authentification).
- **DuckDB : un seul processus écrivain à la fois.** Deux `crawl` en parallèle : le second échoue
  (fichier verrouillé). Collecter séquentiellement.
- **Phenom (P&G, PMI, Givaudan)** : sitemaps par pays, mais URL sans lieu ; il faudrait
  télécharger chaque annonce pour la situer (P&G : 870+ annonces). Pas encore fait.
- **Scan de secrets GitHub** : le HTML archivé peut embarquer des clés publiques de tiers (la
  carte Google Maps des annonces SmartRecruiters a déclenché une alerte le 2026-11-03, sans
  risque : ce n'est pas notre clé). On n'archive que le contenu utile de l'annonce.
- **SuccessFactors, cas non couverts** : SIG (ni lieu dans l'URL ni dans les microdonnées :
  0 offre), Tetra Pak (`sitemap.xml` est un flux RSS), Pictet, CICR-ancien et UNIL (sur
  `career*.successfactors.eu`, interdit par robots.txt). Givaudan est en réalité sur Phenom.
- **Carte des ATS (2026-11-03, `uv run job-rec-ai boards`)** : Workday 13, SuccessFactors 11,
  SmartRecruiters 7, Oracle 3, Phenom 2, et un employeur chacun pour Cornerstone, iCIMS, Workable
  et Softgarden ; 15 employeurs sans ATS identifié (sites maison : État et Ville de Genève, CHUV ;
  protégés : JTI derrière un contrôle anti-robot, Rolex ; Mercuria ne publie que sur LinkedIn).
  Les sites SuccessFactors des employeurs (`jobs.sicpa.com/search/`, `careers.epfl.ch`…)
  autorisent les robots ; les domaines `career*.successfactors.eu`, non.
- **Les URL de board ne sont fiables qu'après une collecte réelle.** Le 2026-11-02, Richemont
  (`wd3`, 404) et PMI (passé chez Phenom) étaient faux ; Caterpillar, Logitech, Medtronic et
  Edwards répondent. `uv run job-rec-ai boards` marque d'un « ? » les boards jamais vérifiés.
- **Le réseau des sessions Claude cloud bloque les ATS** (`*.myworkdayjobs.com`,
  `api.smartrecruiters.com`). Toute collecte réelle, et la création des fixtures
  (`uv run job-rec-ai fixture <entreprise>`), se fait sur le VPS ou en local.
- **Les notes vivent dans Notion** ([base privée](https://app.notion.com/p/b50dbb73996340038d720ae515550d33)).
  `docs/learnings/` (gitignoré) n'en est qu'une copie locale, à recréer depuis Notion en début de
  session : le test `test_premiere_note_de_savoir` en a besoin.

## Prochaines étapes

1. Familles de métiers : 431 offres sur 1 002 dans « Autre » (dont presque toutes les Coop) :
   enrichir `families.py` ou attendre l'extraction par LLM (M5).
2. Décider du sort des annonces sans description (Coop) pour la recommandation.
3. Mesurer la couverture par employeur contre un agrégateur (expérience reportée par Leif) ;
   pistes restantes : État de Vaud, CHUV, Ville de Genève, Migros Genève/Vaud, HCR.
4. Sur le VPS : installer la collecte nocturne ([deploy/README.md](deploy/README.md)).
5. Interpréter ensemble la première sortie de `uv run job-rec-ai quality`.
6. M3 : similarité cosinus (intuition géométrique, exemple 2D), puis TF-IDF from scratch et
   les métriques d'évaluation (precision@k, MRR, nDCG).
7. Finir M0 : règles perso dans `CLAUDE.md`, Milestones GitHub.

## Journal des sessions

- **2026-11-04** (suite) : objectif 1 000 atteint : **1 002 offres actives**, 42 employeurs,
  0 erreur. Connecteurs Oracle (UBP 50, JPMorgan 11, OIM 8), Taleo (OMPI 10, OMS 2), Phenom
  (Givaudan 14, PMI 5, P&G 2), careers.un.org (ONU 48), CERN (31) ; nouveaux employeurs sur
  les ATS existants : Coop 209, EY 36, UIT 18, Fonds mondial 12, PwC 9, IMAD 9, Hospice
  général 5, Clair Bois 3, Securitas 3, OIT 2 ; filtrage par pays côté serveur ; quartiers
  genevois et communes vaudoises ajoutés à `geo`. Revue de la PR #6 : 10 constats traités
  (facette Workday sans valeur reconnue → parcours complet, pagination Taleo selon le
  serveur, échappements JavaScript, dates Taleo et CERN via le flux RSS, pagination de la
  liste CERN, commune/canton SuccessFactors seulement s'ils sont complets).
- **2026-11-04** : revue des PR #3 à #5 (un sous-agent par PR), 10 constats corrigés :
  redirections soumises au robots.txt de leur cible, annonce retirée qui ne fait plus
  échouer l'employeur, veto géo lieu par lieu, pré-filtre Nestlé, dates Java CET, JSON-LD
  robuste et textes nettoyés, canton de repli limité aux sites maison. Collecte complète :
  514 offres actives, 0 erreur (24 vraies expirations depuis la veille).
- **2026-11-03** (suite) : objectif 500 atteint : **523 offres actives**. Richemont raccordé
  (board Workday corrigé : 74 offres), Alcon et Julius Baer ajoutés, connecteur JSON-LD pour
  l'État de Genève (82), canton de repli de l'employeur, réessai sur pannes réseau ;
  `replay` des archives bronze pour appliquer le nouveau parseur sans re-télécharger.
- **2026-11-03** (suite) : connecteur SuccessFactors (EPFL 67, Nestlé 60, BCV 31, CICR 17,
  SICPA 7, Genève Aéroport 1) : 364 offres actives ; correctif `geo` (tirets ≡ espaces,
  coquille Grand-Saconnex) ; alerte de secret GitHub traitée (clé Maps publique de
  SmartRecruiters retirée des archives) ; test d'enrichissement rendu déterministe.
- **2026-11-03** (suite) : connecteur SmartRecruiters réécrit sur le site public ; checkpoint
  M1 à 8/8 ; collecte réelle : 181 offres actives (HUG 47, Lombard Odier 47, Swissquote 28,
  WEF 12, Logitech 10, Trafigura 8, Vitol 8, Proton 7, Nexthink 5…) ; LDC vérifié : 331 offres,
  aucune en Suisse.
- **2026-11-03** (en local) : visite des pages carrière des 43 employeurs sans ATS (client HTTP
  puis navigateur) : 28 ATS identifiés, `companies.csv` complété ; 5 nouveaux boards Workday
  (Lombard Odier, Trafigura, Gunvor, Temenos, WEF) ; collecte réelle : 94 offres (Lombard Odier
  47) ; relevé ponctuel du volume SmartRecruiters.
- **2026-11-02** (en local, réseau ouvert) : fixture Workday réelle (Logitech) ; connecteur
  Greenhouse + fixture (Proton) ; correctif `geo` (les lieux multi-sites citant la Suisse et un
  pays étranger étaient écartés : 3 offres Proton sur 7 perdues) ; boards Richemont et PMI
  corrigés ; première vraie collecte : 24 offres (Logitech 12, Proton 7, Medtronic 4, Edwards 1,
  Caterpillar 0) ; découverte du blocage SmartRecruiters par robots.txt.
- **2026-10-30** : revue et fusion du travail M1/M2 ; première note (venv) ; contrôles qualité
  (alerte d'expiration, commande `quality`, bronze par collecte) ; timer systemd pour le VPS ;
  création de ce fichier ; notes migrées vers Notion ; PR #1 fusionnée.
- **2026-10-22** : M1/M2 : connecteurs Workday et SmartRecruiters, modèle `Job`, DuckDB,
  upsert idempotent, diff de collectes, CLI (`crawl`, `search`, `stats`, `benchmark`…).
