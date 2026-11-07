# Avancement

Le carnet de bord du projet : où on en est, ce qu'on a décidé et pourquoi, la suite.
Les tâches cochables restent dans [ROADMAP.md](ROADMAP.md) ; ce fichier ne les recopie pas.

_Dernière mise à jour : 2026-11-07_

## Où on en est

| Étape | Checkpoint | Ce qui reste |
|---|---|---|
| M0 · Setup | 9/9 (avec une note locale, voir « Contraintes ») | règles perso dans `CLAUDE.md`, Milestones GitHub, questions de contrôle |
| M1 · Collecte | **8/8** (fixtures réelles pour les 13 connecteurs) | **1 692 offres réelles** en Suisse romande francophone (GE 681, VD 511, FR 214, NE 106, BE 83, VS 72, JU 25 ; 58 employeurs et 1 agence). Restent : note HTTP, questions de contrôle |
| M2 · Pipeline | 7/7 (livrable : [notebook « 5 graphiques »](notebooks/marche-emploi.ipynb)) | installer le timer sur le VPS, note ETL/ELT, questions de contrôle |
| M3 · Baseline | code 6/6 ; BM25 en production (`recommend`), nDCG@10 0,779 sur 38 offres notées | 3-4 CV anonymisés de plus, note « mesurer avant d'optimiser », questions de contrôle |
| M4 → M8 | pas commencé | |

Tests du projet : 345 réussis.

## Décisions

- **2026-11-07 · Pages publiques d'offres pour DoxAI : routes `/jobs` et annonces en
  Markdown.** DoxAI ajoute une liste cherchable (`/fr/emplois`) et une page par offre ;
  contrat fixé côté DoxAI, construit en parallèle (`docs/integration-doxai.md`). `GET /jobs`
  (BM25 sur titre + entreprise + description, cantons, taux par recouvrement de plages,
  ancienneté, pagination, facettes par canton calculées sans le filtre canton), `GET /jobs/{id}`,
  `GET /jobs/{id}/similar` ; `/recommend` gagne `id`, son classement est figé par un test
  (relevé sur les 13 fixtures avant le changement). `id` = 16 hex du SHA-256 de l'URL : la
  clé de la base, raccourcie et stable. Tout reste en mémoire (`catalog.py`, fonctions
  pures) : l'API doit répondre pendant la collecte, qui verrouille DuckDB ; un second index
  BM25 (avec l'entreprise) plutôt que de toucher celui de `/recommend`. Le Markdown
  (`markdown.py`, `html.parser` comme `clean_html`) garde titres, listes, gras et liens
  http(s), échappe le reste ; deux conventions d'ATS rattrapées : paragraphe court tout en
  gras = titre, lignes à puces « • » = liste (sections de l'ONU : `<div>` titrés par leur
  classe, convertis dans le connecteur). Vérifié sur les 13 fixtures : mêmes mots que la
  description brute, à part les boutons du CERN. Colonne `jobs.description_markdown`
  (additive) remplie par chaque connecteur ; pour les offres déjà en base,
  `backfill-markdown` re-parse la dernière archive `raw/` de chaque entreprise (sans réseau,
  ~1 min pour 1 700 offres), sinon la collecte suivante s'en charge. `language` de l'API
  précise « other » en `de` / `it` (mots-outils propres à l'API : ceux du moteur ne changent
  pas, le classement non plus).

- **2026-11-06 · Mise en ligne pour DoxAI (M8 avancé, embeddings en pause).** Décisions de
  Leif : API sur le réseau Docker du VPS seulement (pas d'URL publique), image GHCR comme
  DoxAI, intégration par une page de l'app web (Next.js), code préparé ici puis session sur
  le VPS. `api.py` (FastAPI) : `/health`, `/status`, `/recommend {cv_text, k, cantons}` ;
  index BM25 en mémoire, rechargé quand la base change ; base verrouillée pendant la
  collecte → l'index de la veille reste servi ; `storage.connect` réessaie si l'API tient
  le fichier. Projet Compose à part (`/opt/job-rec-ai`, `deploy/docker-compose.yml`) pour ne
  pas toucher `/opt/n8n-stack` ; collecte = même image, `docker compose run crawl`, timer
  systemd ; plafonds mémoire (VPS 4 Go partagé). Contrat côté DoxAI :
  `docs/integration-doxai.md` (route serveur, page, réutilisation de
  `POST /api/v2/opportunities`). Les embeddings (torch, ~1 Go) restent hors de l'image.
- **2026-11-07 · Déployé sur le VPS, branché sur le staging seulement.** Consigne de Leif :
  « Les changements UX/UI -> Déployer sur le staging pas sur prod ». L'API tourne
  (`/opt/job-rec-ai`, conteneur `job-rec-ai`, 1 706 offres, 157 Mo) ; première collecte
  74 min, 125 Mo au pic ; timer actif (03:17 UTC). Variables dans `staging.env` ; la prod
  (`cv-app.env`) n'est pas touchée. `/status` relit désormais la base comme `/recommend` (il
  montrait 0 offre après la collecte jusqu'au premier `/recommend`).
- **2026-11-06 · Revue de PR #14, 9 corrections.** La requête retire les lignes de
  coordonnées (adresse et NPA 1203, e-mail, téléphone, profils) et les nombres purs
  (dates, « 200+ ») : avec les répétitions gardées, ils matchaient des adresses et des
  dates d'offres ; nDCG@10 bm25 · CV 0,775 → 0,779. Le « hasard » n'est plus une méthode
  (son top 10 n'était jamais jugé : 0 par construction) ; le plancher se lit sur les 10
  offres tirées au hasard du pool, retrouvées et enregistrées dans `leif.json`
  (« random ») : 1 notée ≥ 1 → P@10 attendue ≈ 0,10. `load_sets` ignore un JSON qui
  n'est pas un jeu ; `--import` refuse une note hors de 0/1/2 ; le re-pooling garde les
  offres du pool même expirées, met `pooled_at` à jour et ne retire plus 10 offres au
  hasard à chaque appel ; la page d'annotation range les notes du navigateur sous une clé
  propre à sa version ; corpus découpé et index BM25 construits une fois par jeu ;
  scikit-learn retiré (utilisé seulement par un script hors dépôt) ; puces retirées en
  début de ligne seulement.
- **2026-11-05 · BM25 avec répétitions du CV = système par défaut** (décision de Leif sur
  les chiffres ci-dessous). `recommend` et `eval` : « bm25 » est ce système,
  « bm25-dédoublonné » l'ancienne variante. Leif juge le système assez bon pour le
  brancher plus tard sur l'app DoxAI ; à terme, tests A/B/C en ligne entre systèmes une
  fois les embeddings là (M4).
- **2026-11-05 · M3 : premiers chiffres (38 offres notées par Leif : 7 « 2 », 12 « 1 »,
  19 « 0 »).** nDCG@10 : BM25 répété · CV 0,775 ; BM25 répété · profil 0,740 ; TF-IDF · CV
  0,699 ; BM25 dédoublonné · CV 0,662 (mais meilleure P@10, 0,90) ; BM25 · profil 0,617 ;
  TF-IDF · profil 0,249 ; hasard 0. Garder les répétitions du CV gagne sur les deux
  requêtes : elles encodent ce que le CV met en avant (« ia » ×9), ce que Leif confirme
  (« l'IA est pertinente ») ; dédoublonner remonte des offres IT génériques notées 1. Les
  10 offres du hasard seul : neuf 0, un 1. Prudence : une seule personne, 38 notes ;
  0,775 contre 0,740 tient à un échange de rang. « Analyste programmeur » (IMAD), noté 2,
  n'est dans le top 10 que de TF-IDF · profil.
- **2026-11-05 · M3 : jeu d'évaluation (pooling).** Métriques dans `koans` (P@10 avec
  pertinent = note ≥ 1, MRR du premier « 2 », nDCG@10 avec gain = note) : checkpoint M3
  6/6. Un jeu = une personne (`data/private/eval/leif.json` ; personas publics plus tard
  dans `data/eval/`), ses requêtes (CV, `data/private/profil.md` tiré du profil DoxAI par
  le MCP, sans coordonnées ni activités hors cible : serveur, parascolaire, théâtre) et
  ses notes 0/1/2 (adéquation au profil, pas le lieu ni le taux). Pooling façon TREC :
  union des top 10 des 6 classements (TF-IDF, BM25, BM25 répété × CV, profil) + 10 au
  hasard, mélangés et sans score → 38 offres. Recouvrement faible (BM25 · CV et
  TF-IDF · CV : 2 offres communes sur 10). Page `annoter-leif.html` (localStorage,
  « Copier les notes ») ; `eval --import` fusionne ; `eval` affiche P@10, MRR,
  nDCG@10 et la part jugée du top 10. Le corpus d'évaluation garde les offres jugées même
  expirées. Le profil DoxAI donne aussi des contraintes (Genève ou à distance, 80 %
  maximum, hybride) : candidates pour des filtres durs à la requête.
- **2026-11-05 · M3 : BM25.** `bm25.BM25` écrit à la main (index inversé, idf de Lucene
  toujours positif, k1 = 1,2, b = 0,75) ; `recommend.rank` prend le CV comme requête, sans
  mots-outils et dédoublonné (BM25 ne sature rien côté requête : « ia » ×9 compterait 9
  fois) ; commande `job-rec-ai recommend`. L'offre Specitec visée est **1ʳᵉ**, avec un
  score réparti sur 34 mots (le plus gros : 8 %), contre 62 % pour « ia » seul en TF-IDF.
  Le dédoublonnage fait passer « Business Analyst IA » (Specitec) de 3ᵉ à 22ᵉ, et la grille
  k1 × b la déplace de 6ᵉ à 69ᵉ : impossible de dire quel réglage est meilleur avec une
  seule offre jugée pertinente → le jeu d'évaluation d'abord, le réglage ensuite.
- **2026-11-05 · M3 : TF-IDF.** `koans.tfidf` (tf = n/longueur, idf = ln(N/df)) et
  `text.tokenize`. Cosinus TF-IDF : l'offre Specitec visée passe de 75ᵉ à **2ᵉ** (1ʳᵉ :
  Business Analyst IA chez Specitec) ; score médian 0,016 contre 0,27 en tête (le brut
  tassait tout entre 0,62 et 0,64). Limites vues : « et » n'est que dans 39 % des offres
  (anglais, Coop sans description) → idf 0,94, encore 10-40 % du score ; « ia » n'est que
  dans 16 offres (l'anglais écrit « AI ») → idf 4,7, jusqu'à 62 % du score ; mots du seul
  CV (doxai, leif, téléphone) : idf maximal mais contribution nulle. scikit-learn (dev) :
  idf = ln((1+N)/(1+df)) + 1 et tf brut normalisé L2 → valeurs différentes, même
  classement ; tf sous-linéaire (1 + ln tf) met Specitec 1ʳᵉ.
- **2026-11-05 · M3 : texte du CV et premier cosinus.** CV dans `data/private/cv.pdf`
  (non versionné), lu par `cv.read_cv` avec pypdf (pur Python ; une colonne suffit),
  césures recollées, icônes et puces retirées. Expérience : cosinus sur des comptes de
  mots bruts → 96 % du produit scalaire du top 50 vient de mots-outils (« et », « de »,
  « des ») ; le top 10 est fait d'annonces longues en français (Responsable de formation,
  Technicien sanitaire…) ; l'offre Specitec pour laquelle le CV a été écrit arrive 75ᵉ.
  Motive TF-IDF. Le périmètre reste un filtre de collecte (décision de Leif : le premier
  modèle est trop simple pour pénaliser Viège lui-même) ; un filtre dur à la requête
  serait l'alternative sans perte de données.
- **2026-11-05 · Périmètre linguistique, pas cantonal.** Leif a repéré Zermatt parmi les
  offres Helvetia : le Haut-Valais, la Singine (Guin, Tavel), Morat et le Seeland ne sont pas
  la Suisse romande. Révise la décision du 04.11 (« le canton est l'unité »). `geo` les
  écarte même quand le lieu nomme aussi le canton (« Visp, Wallis ») ; les plages de NPA
  sont affinées (Granges SO 2540 était classée BE). `rederive` désactive désormais les
  offres qui perdent leur canton : 192 offres sorties (Lonza Viège 141, Coop 30, Helvetia 5,
  État de Fribourg 5, Groupe E 5, HFR 4, Mobilière 1, Vaudoise 1). Lonza, sans site romand,
  est exclue de la collecte (`blocked`). Limite connue : un même segment de lieu qui cite
  une commune romande et une germanophone (« Sion, Visp ») est écarté.
- **2026-11-05 · Un explorateur d'offres en page statique.** `job-rec-ai explore` écrit
  `data/offres.html` (non versionné, régénéré après une collecte) : les offres actives en JSON
  dans la page, filtres (texte, canton, famille, séniorité, langue, employeur/agence, moins de
  7 jours), regroupement (famille, employeur, canton), tri. Pourquoi pas Streamlit tout de
  suite : aucun serveur, ouverture instantanée, ~2 000 offres se filtrent sans peine dans le
  navigateur ; l'app interactive avec le modèle reste pour M7 (swipes). Testée sur ordinateur
  et téléphone, en thème clair et sombre.
- **2026-11-05 · Connecteur Prospective (Helvetia Baloise).** Le site carrière est une
  application JavaScript ; son code donne l'API publique
  (`ohws.prospective.ch/public/v1/medium/<canal>/jobs`, permise par robots.txt). Champs
  structurés : ville, NPA, pays, introduction, tâches, exigences, domaine, taux. Lieu
  « Ville, CH-NPA » : le NPA situe les communes inconnues de geo. Pas de date de publication
  dans l'API (`posted_at` vide). 36 offres en Suisse romande sur 156 en Suisse (41 avant
  le périmètre linguistique : Zermatt, Viège, Guin et Granges en sont sortis).
- **2026-11-05 · Revue de PR #9 et #10.** L'URL d'une offre est sa clé : le connecteur JSON-LD
  retire les paramètres de suivi (`jobDbPVId` de softgarden, `utm_*`) ; les 45 URL Vaudoise
  déjà en base ont été réécrites (pas de faux doublon, `first_seen` gardé). Colonne `blocked`
  dans `companies.csv` : la raison d'une exclusion (robots.txt, 403, jobboard), l'`ats` reste
  un fait ; `boards` liste les exclues à part (16). Un board SuccessFactors avec un chemin ne
  lit que ses annonces du sitemap (`careers.mediclinic.com/Hirslanden` : plus de pages
  sud-africaines téléchargées pour rien). Workable lit le canton dans `region`. Un code de
  canton nu (« FR ») est lu entre parenthèses ; « Schweiz », « CHE »… valent la Suisse pour le
  NPA ; une pagination annoncée mais non suivie est signalée dans le journal.
- **2026-11-05 · Deux connecteurs de plus, et le JSON-LD élargi.** Workable (API publique du
  widget : Debiopharm, 8 offres) et Cornerstone (le jeton anonyme de la page carrière publique,
  comme le navigateur : MSC 11, Groupe Mutuel 19). Cornerstone : un petit board est lu en
  entier et filtré ici (Groupe Mutuel ne donne pas le pays), un grand est filtré sur la Suisse
  par le serveur. JSON-LD : « <liste>#jobs=<chemin> » quand les annonces ne sont pas sous la
  liste (softgarden : Vaudoise 45 ; Radancy : Cargill 4, première page seulement), et la région
  quand la ville manque. Restent hors connecteur, avec leur raison : SuccessFactors ancienne
  génération et Eightfold (robots.txt l'interdit : Manor, Aldi, Lidl, Implenia, Haleon),
  Umantis (gabarit propre à chaque client, lieu non structuré : Generali, UniNE), Avature
  (flux RSS mondial sans lieu : HSBC, Takeda), Prospective (Helvetia, connecteur ajouté depuis :
  Baloise), Jibe/iCIMS (API ouverte mais 1 offre suisse : Swissport).
- **2026-11-05 · Les grands employeurs genevois (classement 1999/2019) et le commerce de
  détail.** Ajoutés et collectés : Hirslanden (SuccessFactors de Mediclinic), Zurich
  Assurances, La Mobilière (SuccessFactors), HP et HPE (Workday). 26 autres listés dans
  `companies.csv` avec la raison dans la colonne `ats` : `successfactors-classic` (Manor,
  Lidl, Aldi, Implenia : l'ancienne génération, sans sitemap ; Lidl l'interdit par
  robots.txt), `cornerstone` (MSC, Groupe Mutuel : un connecteur couvrirait les deux),
  `umantis` (Generali, UniNE), `prospective` (Helvetia Baloise), `icims` (Swissport),
  `avature` (HSBC) ; vide = site maison ou qui refuse notre robot (Migros, Fnac, UBS, BNP,
  La Tour : 403). Hors liste, sans plateforme de recrutement (annonces sur jobup) : Dosim,
  Top Net, Cleaning Service, Laiteries Réunies. Disparus ou absorbés : SAirGroup, Credit
  Suisse (UBS), United European Bank (BNP), Zschokke (Implenia), Charmilles (GF Machining
  Solutions).
- **2026-11-05 · Le NPA comme indice de lieu.** Mediclinic tronque la ville (« Laus ») mais
  publie le code postal : un NPA 1000-2999 donne le canton par plages approximatives
  (`geo._NPA_RANGES`), seulement préfixé « CH- » ou dans un lieu qui nomme la Suisse
  (Bruxelles 1000, Sandton 2196 ont aussi 4 chiffres). Le pré-filtre d'URL SuccessFactors
  l'accepte aussi (« …-Laus-1003 »), sauf 2000-2099 (des années). Hirslanden : 26 → 58 offres.
- **2026-11-05 · Les agences de placement entrent, marquées.** Colonne `publisher_type`
  (« employeur » par défaut, « agence ») dans `companies.csv`, la table `companies` et la vue
  `jobs_view` ; facette `--publisher_type` dans `search` et `stats`. Pourquoi : une agence
  publie des postes absents ailleurs (le marché caché), mais souvent sans le nom du client et
  parfois en double avec l'employeur ; le marqueur permettra de dédoublonner et de pondérer
  (M6). Collectée : Specitec (Teamtailor, JSON-LD, 15 offres). Listées sans connecteur :
  Michael Page, Randstad, Adecco, Manpower, Interiman, Hays, Academic Work (robots.txt
  interdit `/api/`), Robert Walters (403) : sites maison sans JSON-LD. Les jobboards
  (SwissDevJobs, jobs.ch, jobup) restent hors source : ils republient les annonces des
  employeurs ; ils servent de repère (benchmark), comme Adzuna.
- **2026-11-04 · Périmètre élargi à toute la Suisse romande** (GE, VD, FR, NE, VS, JU et le
  Jura bernois avec Bienne, sous le code BE). Décision de Leif après la mesure (≈ +270 offres
  en élargissant seulement le filtre, dont ~190 Coop) : on élargit **et** on ajoute des
  employeurs locaux. Six trouvés avec un ATS déjà supporté : État de Fribourg et Groupe E
  (SuccessFactors), HFR (Oracle), UCB Bulle (Phenom), Lonza Viège (Workday), CSEM
  (JSON-LD). Résultat : 1 001 → **1 650 offres**, 42 → 49 employeurs. Le VS germanophone
  (Viège, Brigue) est inclus : le canton est l'unité, la langue reste un filtre (révisé le
  05.11 : périmètre linguistique, voir plus haut). Abréviations
  des nouveaux cantons seulement entre parenthèses (« Bulle (FR) ») : « FR », « BE », « NE »
  nus sont aussi des codes de pays ; veto ajouté pour l'Allemagne (Freiburg im Breisgau).
  Revue de PR #8 (05.11) : le connecteur JSON-LD filtre aussi le lieu quand l'annonce nomme
  sa ville (CSEM publiait Alpnach, Allschwil : 6 offres hors périmètre, étiquetées NE) ;
  veto « breisgau », « am Rhein », « , DE » ; homonymes VD/NE (Colombier, Corcelles,
  Fontaines) et « Fully » retirés des listes ; le canton tronqué de Coop (« Neuc », « Vala »)
  est complété, dans le lieu comme dans le pré-filtre d'URL (+18 offres Coop). 1 657 offres.
- **2026-11-04 · Le classement déclaré par l'ATS, quand il existe, complète le titre.**
  Colonnes `category` et `level` (texte brut de l'ATS, aujourd'hui SuccessFactors seulement ;
  SmartRecruiters publie aussi `function` et `experienceLevel` : à brancher). La famille vient
  du titre, à défaut de la catégorie ; la séniorité du titre, puis du niveau, puis des années
  d'expérience. Mots-clés ajoutés pour le commerce de détail et les métiers de bouche.
  « Autre » : 431 → 317 offres (Coop 173 → 60). Les « Gestionnaire du commerce de détail
  CFC » de Coop sont sans doute des places d'apprentissage, mais le titre ne le dit pas :
  laissées « Non précisé » (cohérent avec « Électricien CFC »).
- **2026-11-04 · Élargir à toute la Romandie : mesuré, pas fait.** Mêmes 48 employeurs, filtre
  FR / NE / VS / JU / Jura bernois : **≈ +270 offres (+27 %), dont ~190 annonces Coop**
  sans description ; hors Coop ≈ +75 (Richemont 35, EPFL 11, PMI 8, Nestlé 7, Alcon 4…).
  Élargir le filtre ne multiplie pas la base : les employeurs ont été choisis pour GE/VD.
  Ce qui la multiplierait, ce sont les employeurs locaux (cantons, hôpitaux, Groupe E, CSEM,
  Swatch…). Décision de périmètre laissée à Leif ; scripts de mesure hors dépôt.
- **2026-11-04 · Séniorité : le titre, sinon les années d'expérience de la description.**
  Le défaut s'appelle désormais « Non précisé » (il valait « Confirmé·e », ce qui affirmait
  un niveau sans indice : 56 % des offres). Ajout de postdoc / PhD / graduate → Junior. Une
  fourchette (« 2 to 5 years ») compte pour son milieu ; ≤ 2 ans Junior, ≤ 5 Confirmé·e,
  au-delà Senior / Lead. Résultat : « Non précisé » 561 → 342 (dont 129 Coop), Junior 7 → 94.
  Revue de PR #7 : une mention de plus de 15 ans est l'histoire de la maison (« fort de 25 ans
  d'expérience, notre cabinet… »), on passe à la suivante ; « 1 an », « une année » reconnus ;
  « cadre » ne compte que dans le niveau déclaré par l'ATS (« Futur cadre junior », « Relève
  futur·e cadre » sont des programmes de relève → Junior).
  Graphique bonus dans le notebook. La M5 (extraction par LLM) devra battre ces règles.
- **2026-11-04 · Une collecte interrompue est signalée par `quality`.** Table `crawls` : une
  ligne par collecte, avec la liste des entreprises prévues ; `finished_at` n'est écrit qu'à la
  fin (pas dans un `finally`, sinon un Ctrl-C passerait pour une collecte complète). Expérience
  du crash à 60 % : pas de doublon ni de fausse expiration (expiration par entreprise, après sa
  collecte), mais les 40 % restants gardaient des offres périmées sans aucune trace. Pas de
  reprise (« checkpoint ») : la collecte est idempotente, tout relancer est juste, et une
  reprise ne ferait gagner que du temps. Pas de réordonnancement automatique de l'entreprise
  « poison » : les erreurs Python sont déjà isolées par entreprise ; à reconsidérer si un même
  employeur fait tomber le processus deux fois.
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

- **SuccessFactors, des descriptions maigres** (rapport qualité du VPS, 06.11) : 46 % des
  offres ont moins de 300 caractères de description et 25 % ne sont ni en français ni en
  anglais (surtout Coop, en allemand). Peu de mots en commun avec un CV : BM25 les classe mal.
- **Coop : des annonces sans description** (titre, taux, référence seulement : c'est ce que
  publie Coop). 209 offres sur 1 002, presque toutes classées « Autre » et en langue « other »
  (texte trop court pour la détection). À pondérer, voire à écarter, pour la recommandation.
  Vérifié le 04.11 sur la page elle-même : le bloc « description » ne contient que le titre.
  La page a en revanche des champs « libellé : valeur » (`data-careersite-propertyid`),
  archivés depuis le 04.11 (`details` dans le bronze) : « Spécialisation professionnelle »
  → colonne `category`, « Poste » → `level`. Coop ne les remplit que sur ~60 annonces sur
  204 (pas sur les apprentissages ni les stages d'orientation).
- **Sans connecteur possible pour l'instant** : UNIGE (contrôle anti-robot « Vérification de
  sécurité »), TPG (403), Edmond de Rothschild (offres suisses sans ville), OMC (lieu « CWR »),
  Ferring (pas d'offre suisse sur son board Workday), API WordPress du CERN (authentification).
  Romandie (04.11) : Université de Neuchâtel (Umantis), RHNe et BCN (annonces sur jobup
  seulement), Takeda (Avature), BMS (robots.txt l'interdit), Swatch Group (site qui ne
  répond pas au robot) ; État de Neuchâtel, État du Valais, Hôpital du Valais, canton du Jura,
  Hôpital du Jura, Syngenta, Tornos, Sonceboz : ATS non identifié (sites maison, à creuser).
- **Offres en allemand** depuis l'élargissement (Lonza, Coop Haut-Valais, État de Fribourg) :
  ~280 offres en langue « other », et des titres que les règles FR/EN ne classent pas.
  Quelques mots-clés allemands ajoutés ; le reste attend l'extraction par LLM (M5).
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

1. Familles de métiers : 667 offres sur 1 884 dans « Autre » (Coop, Lonza, État de
   Fribourg) : enrichir `families.py` (allemand surtout) ou attendre l'extraction par LLM (M5).
2. Romandie : identifier l'ATS des États de Neuchâtel, du Valais et du Jura et de l'Hôpital
   du Valais (gros employeurs locaux, pas encore couverts).
3. Décider du sort des annonces sans description (Coop) et des offres d'agence (doublons
   avec l'employeur, client anonyme) pour la recommandation (M6).
4. Mesurer la couverture par employeur contre un agrégateur (expérience reportée par Leif) ;
   pistes restantes : État de Vaud, CHUV, Ville de Genève, Migros Genève/Vaud, HCR.
5. DoxAI : voir la page « Offres recommandées » sur le staging (label `staging` sur
   mieleif/cv-app-web#129, à poser par Leif), puis décider du passage en prod
   ([deploy/README.md](deploy/README.md), « Brancher DoxAI »). Routes `/jobs` : déployer
   l'image (deploy/README.md, « Mise à jour du 07.11.2026 ») puis `backfill-markdown`, sur
   accord du propriétaire du VPS ; relire quelques annonces réelles en Markdown (Coop,
   SuccessFactors) une fois en ligne.
6. Interpréter ensemble la première sortie de `uv run job-rec-ai quality` (elle est dans
   `journalctl -u job-rec-ai-crawl` sur le VPS) ; journaliser la collecte source par source
   au fil de l'eau (aujourd'hui : rien pendant 75 min, puis le résumé).
7. M3 : vérifier que BM25 généralise au-delà du profil de Leif. Contrainte (Leif,
   06.11) : il ne peut pas juger la pertinence d'offres pour des métiers qu'il n'a pas.
   Pistes : CV et notes de vrais amis (rejoint « faire tester par 3 amis » de M7), ou un
   LLM juge (M5) calibré d'abord sur les 38 notes de Leif (accord mesuré). Note « mesurer
   avant d'optimiser » écrite.
   Filtres durs à la requête tirés du profil DoxAI (Genève ou à distance, 80 % maximum).
   Plus tard : brancher `recommend` sur l'app DoxAI ; tests A/B/C (interleaving) en M4-M7.
8. Finir M0 : règles perso dans `CLAUDE.md`, Milestones GitHub.

## Journal des sessions

- **2026-11-07** (suite) : routes `/jobs` pour les pages publiques d'offres de DoxAI
  (liste, détail en Markdown, offres semblables), `id` dans `/recommend`, colonne
  `description_markdown` et commande `backfill-markdown` ; 345 tests.
- **2026-11-07** : image publiée (PR #16, YAML du workflow réparé), API déployée sur le VPS,
  staging DoxAI branché ; README de déploiement corrigé d'après le terrain ; `/status` relit
  la base.
- **2026-11-06** (suite) : API FastAPI, Dockerfile, CI et image GHCR, déploiement Docker
  pour le VPS de DoxAI, contrat d'intégration ; checkpoint M8 (API) 3/3.
- **2026-11-06** : revue de PR #14, 9 corrections (requête sans coordonnées ni nombres,
  plancher du hasard mesuré, re-pooling idempotent) ; nDCG@10 0,779.
- **2026-11-05** (après-midi) : PR #12 et #13 fusionnées ; M3 commencé (cosinus, texte du
  CV, expérience du cosinus brut : l'offre visée 75ᵉ ; TF-IDF : 2ᵉ ; BM25 : 1ʳᵉ) ;
  métriques, pooling de 38 offres, page d'annotation, 38 notes de Leif : BM25 répété
  en tête (nDCG@10 0,775), devenu le système par défaut.
- **2026-11-05** (matin) : périmètre linguistique (Zermatt repéré par Leif) ; Haut-Valais,
  Singine, Morat et Seeland écartés ; 1 884 → 1 692 offres, Lonza exclue.
- **2026-11-05** (fin) : explorateur d'offres (`explore`, `data/offres.html`).
- **2026-11-05** (nuit, suite) : connecteur Prospective, Helvetia Baloise collectée (41).
  1 884 offres, 60 sources.
- **2026-11-05** (nuit) : revue de PR #9 et #10, 8 corrections ; le travail Romandie (PR #8,
  fusionnée dans une branche déjà fusionnée) ramené sur `main`.
- **2026-11-05** (soir) : connecteurs Workable et Cornerstone ; JSON-LD avec chemin
  d'annonces (softgarden, Radancy) ; Debiopharm, MSC, Groupe Mutuel, Vaudoise, Cargill
  collectés. 1 843 offres, 59 sources.
- **2026-11-05** (fin) : marqueur « agence » (`publisher_type`) ; Specitec collectée ;
  8 autres agences listées. 1 756 offres.
- **2026-11-05** (suite) : grands employeurs genevois et commerce de détail passés en revue
  (31 ajoutés à la liste, 5 collectés : Hirslanden, Zurich, Mobilière, HP, HPE) ; NPA comme
  indice de lieu ; étude des agences et jobboards. 1 741 offres, 53 employeurs.
- **2026-11-05** : revue de PR #7 et #8, corrections : séniorité (cadre, histoire de la maison,
  singulier), l'alerte « collecte interrompue » survit à une collecte partielle, `rederive` par
  noms de colonnes, case « Identifier l'ATS » décochée (24 employeurs sans ATS identifié) ;
  CSEM hors périmètre écarté, homonymes allemands et vaudois, canton tronqué de Coop.
- **2026-11-04** (nuit) : périmètre élargi à la Suisse romande ; 6 employeurs locaux ajoutés
  (État de Fribourg, Groupe E, HFR, UCB, Lonza, CSEM) ; 1 650 offres, 0 erreur ; graphique
  par canton dans le notebook.
- **2026-11-04** (soir) : version HTML du notebook (`docs/marche-emploi.html`) ; expérience du
  crash à 60 % ; alerte « collecte interrompue » dans `quality` (table `crawls`) ; séniorité
  par les années d'expérience + graphique ; pourquoi Coop n'a pas de description (il n'en
  écrit pas) et lecture de ses champs structurés ; mesure de l'élargissement à la Romandie.
- **2026-11-04** (fin) : livrables M1 et M2 : notebook `notebooks/marche-emploi.ipynb`
  (top 20 des employeurs, langues, familles, secteurs, âge des offres ; images dans
  `docs/img/`, deux dans le README). Lecture : 53 % d'offres en anglais, 43 % en « Autre »
  (dont 173 Coop), âge médian 15 jours, 26 offres de plus de 6 mois. CLI : sortie forcée en
  UTF-8 (`boards` plantait dans la console Windows sur « ✓ »).
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
