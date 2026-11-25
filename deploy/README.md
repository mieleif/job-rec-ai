# Déploiement sur le VPS de DoxAI : l'API et la collecte nocturne

job-rec-ai tourne sur le même VPS que DoxAI, en conteneurs, à côté de la pile `/opt/n8n-stack`
**sans la modifier** : c'est un projet Compose à part, dans `/opt/job-rec-ai`.

```
            réseau Docker n8n-stack_default (pas d'URL publique)
 staging-web ─┐
 (cv-app) ────┴── POST http://job-rec-ai:8000/recommend ──▶ job-rec-ai (API, BM25 en mémoire)
                                                                  │ lit (lecture seule)
 timer systemd 03:17 UTC ──▶ docker compose run crawl ──écrit──▶ volume data : jobs.duckdb + raw/
```

| Quoi | Où |
|---|---|
| Fichier Compose, `.env` (jeton, chmod 600) | `/opt/job-rec-ai/` |
| Collecte nocturne | `/etc/systemd/system/job-rec-ai-crawl.{service,timer}` |
| Base `jobs.duckdb` et réponses brutes `raw/` | volume Docker `job-rec-ai_data` |
| Le conteneur | `docker ps` → `job-rec-ai` (un conteneur n'est pas dans un dossier : Docker le gère) |

- **Image** : `ghcr.io/mieleif/job-rec-ai:<sha>` et `:latest`, publiques, publiées par
  `.github/workflows/image.yml` à chaque push sur `main` (un tag immuable par commit, comme DoxAI).
- **API** : `GET /health` (sans jeton), `GET /status`, `POST /recommend` et les pages
  d'offres `GET /jobs`, `GET /jobs/{id}`, `GET /jobs/{id}/similar` (jeton
  `Authorization: Bearer $JOB_REC_TOKEN`, sinon 401). Voir `src/job_rec_ai/api.py` et
  [docs/integration-doxai.md](../docs/integration-doxai.md). Joignable seulement depuis le réseau
  Docker de DoxAI, sous le nom `job-rec-ai`.
- **Collecte** : le même conteneur, commande `crawl`, lancée chaque nuit par un timer systemd.
  L'horloge du VPS est en UTC : 03:17 UTC = 04:17 en hiver, 05:17 en été (heure suisse). Une
  collecte romande durait **environ 75 minutes** au premier déploiement (Coop seul : 10 à 15 min, à cause des pauses entre
  requêtes). Le journal reste muet jusqu'au résumé final : `journalctl -f` n'est pas bloqué.
- **Rechargement** : l'API ne relit pas la base d'elle-même. Elle la relit à la requête suivante
  (`/recommend` ou `/status`) si le fichier a changé, au plus une fois toutes les 5 minutes.
  Pendant la collecte, la base est verrouillée en écriture et l'API sert l'index de la veille.
- **Mémoire** (mesurée au premier déploiement, 1 706 offres) : API 157 Mo (plafond 384 Mo),
  collecte ≈ 125 Mo au pic (plafond 768 Mo) ; il est resté ≥ 1,4 Go libres sur les 4 Go partagés
  avec la production DoxAI. Volume de données : 11 Mo.

## Installation (une fois, en SSH)

```bash
# 1. Le dossier du projet et ses fichiers
sudo mkdir -p /opt/job-rec-ai && sudo chown "$USER" /opt/job-rec-ai && cd /opt/job-rec-ai
for f in docker-compose.yml job-rec-ai-crawl.service job-rec-ai-crawl.timer; do
  curl -fsSLO "https://raw.githubusercontent.com/mieleif/job-rec-ai/main/deploy/$f"; done
printf 'JOB_REC_TOKEN=%s\nJOB_REC_TAG=latest\n' "$(openssl rand -hex 32)" > .env && chmod 600 .env

# 2. Vérifier le nom du réseau Docker de DoxAI (sinon : DOXAI_NETWORK=… dans .env)
docker network ls | grep n8n-stack

# 3. L'API (elle répond 503 à /recommend tant qu'il n'y a pas de base : c'est normal)
docker compose pull api && docker compose up -d api
docker exec cv-app wget -qO- http://job-rec-ai:8000/health

# 4. Le timer, puis une première collecte tout de suite (≈ 75 min)
sudo cp job-rec-ai-crawl.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now job-rec-ai-crawl.timer
sudo systemctl start --no-block job-rec-ai-crawl
```

Variante plus rapide pour l'étape 4 : copier une base existante (`scp data/jobs.duckdb vps:/tmp/`
depuis le PC), puis
`docker compose run --rm --no-deps -v /tmp:/import crawl sh -c 'cp /import/jobs.duckdb /srv/data/'`.

Vérifier après la collecte (le jeton est lu dans `.env`, jamais affiché) :

```bash
set -a; . /opt/job-rec-ai/.env; set +a
docker exec cv-app wget -qO- --header "Authorization: Bearer $JOB_REC_TOKEN" http://job-rec-ai:8000/status
```

## Brancher DoxAI

Le jeton est le même des deux côtés : celui de `/opt/job-rec-ai/.env`. Sans `JOB_REC_URL`, la
fonctionnalité reste masquée dans DoxAI.

```
JOB_REC_URL=http://job-rec-ai:8000
JOB_REC_TOKEN=<la valeur de /opt/job-rec-ai/.env>
```

- **Staging d'abord** : ces deux lignes dans `/opt/n8n-stack/staging/staging.env`. Le conteneur
  `staging-web` les prend au prochain déploiement staging (`scripts/staging-vps.sh`, label
  `staging` sur la PR de cv-app-web). `staging-web` est déjà sur `n8n-stack_default`.
- **Production, sur décision de Leif** : les mêmes lignes dans `/opt/n8n-stack/cv-app.env`, puis
  depuis `/opt/n8n-stack` :
  `docker compose -f docker-compose.yml -f docker-compose.cv-app-release.yml up -d --force-recreate --no-deps cv-app`.

## Activer la recherche hybride (25.11.2026)

Sans les étapes ci-dessous, la nouvelle image sert exactement le BM25 d'avant. **À décider par
Leif**, après les notes des 54 offres.

1. Dans `/opt/job-rec-ai/.env` (chmod 600), de préférence une clé Infomaniak **dédiée**, pour
   séparer les coûts de DoxAI : `INFOMANIAK_API_TOKEN=…` et `INFOMANIAK_PRODUCT_ID=…`
   (facultatifs : `JOB_REC_BUDGET_CHF`, 2 CHF par mois et par processus par défaut, puis repli
   BM25 ; `JOB_REC_RERANK=1`, le reranker Qwen3, éteint par défaut).
2. Recopier `docker-compose.yml` (`mem_limit` de l'API : 768 Mo) et
   `job-rec-ai-crawl.service`, puis `sudo systemctl daemon-reload`.
3. Encoder les offres une première fois (~0,16 CHF) :
   `docker compose --profile crawl run --rm crawl job-rec-ai embed`.
4. `docker compose up -d api`, puis `GET /status` : `"ranking": "hybrid"`. `fallbacks` compte
   les replis depuis le démarrage : s'il monte, l'API d'embeddings est lente ou en panne.

**Revenir en arrière** : retirer `INFOMANIAK_API_TOKEN` et relancer l'API.

Mémoire mesurée sous Windows (5 216 offres ; à mesurer sous Linux) : BM25 302 Mo, 438 Mo au pic
d'un rechargement ; hybride 356 et 555 Mo. **L'ancien plafond de 384 Mo était déjà sous le pic
de BM25 seul** sur le corpus national. Disque : 16 Ko par texte distinct (~55 Mo) ; `--prune`
retire les offres disparues.

## Au quotidien

```bash
cd /opt/job-rec-ai
systemctl list-timers job-rec-ai-crawl.timer          # prochaine collecte (heure UTC)
sudo systemctl start job-rec-ai-crawl                 # lancer une collecte maintenant
journalctl -u job-rec-ai-crawl -n 100                 # résumé et rapport qualité de la dernière
docker compose logs --tail 50 api                     # requêtes servies (jamais le texte des CV)
docker compose pull && docker compose up -d api       # mettre à jour (JOB_REC_TAG dans .env)
```

Données à sauvegarder : le volume `job-rec-ai_data` (`jobs.duckdb` et `raw/`). La base se
reconstruit à partir de `raw/` (`docker compose --profile crawl run --rm crawl job-rec-ai replay`).

## Mise à jour du 07.11.2026 : routes `/jobs` et annonces en Markdown

Purement additif : `/recommend` garde ses entrées, ses champs et son classement (vérifié par un
test sur les 13 fixtures) et gagne un champ `id`. La base gagne une colonne
`jobs.description_markdown` (`ALTER TABLE … ADD COLUMN IF NOT EXISTS`, NULL au départ),
ajoutée par le premier processus qui ouvre la base **en écriture** (collecte ou
`backfill-markdown`) ; l'API, en lecture seule, fonctionne avant comme après (sans la colonne,
elle tire le Markdown du texte brut). Ni le fichier Compose, ni les noms de services, ni le timer
ne changent. Le conteneur `job-rec-ai` sert le staging comme la production de DoxAI : c'est le
seul redémarrage (quelques secondes, l'index se recharge au démarrage).

```bash
cd /opt/job-rec-ai
# 1. L'image du commit de main qui contient la mise à jour (ou « latest »)
sed -i 's/^JOB_REC_TAG=.*/JOB_REC_TAG=<sha>/' .env
docker compose pull api && docker compose up -d api     # recrée le seul conteneur job-rec-ai
docker exec cv-app wget -qO- http://job-rec-ai:8000/health

# 2. Remplir le Markdown tout de suite, depuis les archives raw/ (sans réseau, ~1-2 min ;
#    pas pendant la collecte de 03:17 UTC, qui verrouille la base). Sinon, la collecte
#    suivante le remplit d'elle-même pour toutes les offres actives.
systemctl is-active job-rec-ai-crawl            # « inactive » : la voie est libre
docker compose --profile crawl run --rm crawl job-rec-ai backfill-markdown

# 3. Vérifier (l'API relit la base au plus 5 min après)
set -a; . /opt/job-rec-ai/.env; set +a
docker exec cv-app wget -qO- --header "Authorization: Bearer $JOB_REC_TOKEN" \
  "http://job-rec-ai:8000/jobs?per_page=1"
```

Retour arrière : remettre l'ancien `JOB_REC_TAG` et `docker compose up -d api`. L'ancienne
version ignore la colonne ajoutée (elle lit ses colonnes par leur nom) ; rien à défaire dans
la base.

## Mise à jour du 07.11.2026 (2) : domaine des employeurs, pour les logos de DoxAI

Purement additif : chaque offre de `/jobs`, `/jobs/{id}`, `/jobs/{id}/similar` et `/recommend`
gagne `company_domain` (« vitol.com », `null` si inconnu) ; rien n'est renommé ni retiré, le
classement de `/recommend` ne bouge pas (test sur les 13 fixtures). La base gagne une table
`company_domains` (le cache) et une colonne `companies.domain`, créées par le premier processus
qui ouvre la base en écriture ; l'API, en lecture seule, répond `null` tant qu'elles n'existent
pas. La résolution tourne à la fin de chaque collecte : le service `crawl` reçoit donc
désormais `.env` (`env_file`), pour `LOGO_DEV_SECRET_KEY`. Sans cette clé, la recherche
logo.dev est sautée en silence ; les domaines de `companies.csv` (les 65 sources collectées)
sont écrits quand même.

```bash
cd /opt/job-rec-ai
# 1. Le fichier Compose (le service crawl gagne env_file: .env) et la clé (déjà là : « 1 »)
curl -fsSLO https://raw.githubusercontent.com/mieleif/job-rec-ai/main/deploy/docker-compose.yml
grep -c '^LOGO_DEV_SECRET_KEY=' .env

# 2. L'image du commit de main qui contient la mise à jour
sed -i 's/^JOB_REC_TAG=.*/JOB_REC_TAG=<sha>/' .env
docker compose pull api && docker compose up -d api     # recrée le seul conteneur job-rec-ai
docker exec cv-app wget -qO- http://job-rec-ai:8000/health

# 3. Remplir les domaines tout de suite (sinon : à la fin de la prochaine collecte). Pas
#    pendant la collecte de 03:17 UTC, qui verrouille la base. --companies est nécessaire :
#    la commande remplace celle du service.
systemctl is-active job-rec-ai-crawl            # « inactive » : la voie est libre
docker compose --profile crawl run --rm crawl \
  job-rec-ai --companies /app/companies.csv resolve-domains

# 4. Vérifier (l'API relit la base au plus 5 min après)
set -a; . /opt/job-rec-ai/.env; set +a
docker exec cv-app wget -qO- --header "Authorization: Bearer $JOB_REC_TOKEN" \
  "http://job-rec-ai:8000/jobs?per_page=1"     # « company_domain »: "…"
```

Durée de l'étape 3 : **quelques secondes** aujourd'hui. Les 65 sources collectées ont leur
domaine dans `companies.csv` : logo.dev n'est appelé pour aucune. Une entreprise sans domaine
coûte un appel (≈ 1 à 2 s, une pause d'une seconde entre deux appels), une seule fois : le
résultat est mis en cache (un « pas trouvé » est redemandé après 30 jours, une erreur de l'API
à la collecte suivante). La commande affiche ce qu'elle a trouvé, pas trouvé, ou raté.

Corriger un mauvais domaine : une ligne dans `data/company_domains.csv`
(`company,domain,reason` ; domaine vide = pas de logo), ou la colonne `domain` de
`data/companies.csv`, puis une PR ; une fois la nouvelle image en place, l'étape 3 (ou la
collecte suivante) applique la correction.

Retour arrière : remettre l'ancien `JOB_REC_TAG` et `docker compose up -d api`. L'ancienne
version ignore la table et la colonne ajoutées ; `env_file` sur `crawl` est sans effet pour elle.


## Mise à jour du 15.11.2026 : collecte dans toute la Suisse

Le filtre géographique couvre désormais les **26 cantons**, y compris les régions
alémaniques, le Tessin et le Haut-Valais. Lonza est réactivée ; les pré-filtres SuccessFactors
acceptent aussi les lieux et NPA hors Romandie. Aucune migration de schéma, aucune nouvelle
dépendance, aucun changement du contrat API. Le catalogue d'employeurs reste celui de
`companies.csv` ; les noms de communes et correspondances NPA/canton restent partiels.

**L'installation existe déjà** : ne pas refaire l'installation ni régénérer `.env`. Après
fusion et publication de l'image GHCR, choisir le SHA complet de ce commit de `main` pour
`JOB_REC_TAG`. Le push GitHub publie une image ; il ne met pas à jour le VPS automatiquement.
L'API et le prochain conteneur de collecte doivent utiliser cette même version.

1. Attendre la fin de toute collecte en cours (`systemctl status job-rec-ai-crawl`).
2. Dans `/opt/job-rec-ai/.env`, conserver l'ancien `JOB_REC_TAG` pour le retour arrière,
   puis mettre le nouveau SHA. Conserver les jetons existants.
3. Exécuter le bloc suivant sur le VPS. Il suspend le timer pendant la mise à jour et le
   réactive en sortie ; si une collecte est encore active, il s'arrête avant de toucher l'API.

```bash
(
  set -e
  cd /opt/job-rec-ai
  sudo systemctl stop job-rec-ai-crawl.timer
  trap 'sudo systemctl start job-rec-ai-crawl.timer' EXIT
  if systemctl is-active --quiet job-rec-ai-crawl; then
    echo 'Une collecte tourne encore : attendre sa fin, puis relancer.'
    exit 1
  fi
  docker compose pull api
  docker compose up -d api
  docker exec cv-app wget -qO- http://job-rec-ai:8000/health
  sudo systemctl start --no-block job-rec-ai-crawl
)
```

Une **nouvelle collecte complète** est nécessaire : `rederive` ne télécharge rien, et `replay`
ne retrouve pas les annonces rejetées avant leur archivage. Les offres déjà présentes gardent
leur URL et leur identifiant ; les anciennes offres Lonza encore publiées sont réactivées par
l'upsert. Pendant la collecte, l'API conserve son dernier index disponible. À la fin, une
requête recharge la base au plus tard après le délai de rafraîchissement (5 minutes).

```bash
cd /opt/job-rec-ai
journalctl -u job-rec-ai-crawl -n 100
# Après la fin de la collecte : répartition par canton et rapport qualité
# (jamais un second processus d'écriture en parallèle).
docker compose --profile crawl run --rm crawl job-rec-ai stats canton
docker compose --profile crawl run --rm crawl job-rec-ai quality
set -a; . /opt/job-rec-ai/.env; set +a
docker exec cv-app wget -qO- --header "Authorization: Bearer $JOB_REC_TOKEN" \
  "http://job-rec-ai:8000/jobs?cantons=ZH,BS,TI&per_page=3"
docker stats --no-stream job-rec-ai
```

Vérifier les nouvelles facettes, les erreurs et les expirations suspectes. Les **75 minutes,
157 Mo d'API et 125 Mo de collecte** ci-dessus sont les mesures du corpus romand, pas une
prévision nationale. Les plafonds restent 384 Mo (API), 768 Mo (collecte), 3 h (service) :
mesurer le premier passage avant de les ajuster sur ce VPS partagé. Si le service atteint 3 h,
le journal et `quality` signalent la collecte interrompue ; le périmètre national n'est alors
pas encore entièrement collecté. BM25 conserve son algorithme, mais ses scores et son
classement peuvent changer avec la taille et les langues du corpus.

Retour arrière : remettre l'ancien tag, tirer l'image et recréer l'API. Les nouvelles offres
restent dans la base jusqu'à une nouvelle collecte avec l'ancien périmètre ; revenir à
l'ancienne image seule ne restaure donc pas le corpus romand. Lonza, ignorée par l'ancienne
configuration, conserve ses lignes : restaurer une sauvegarde d'avant la mise à jour si un
retour exact aux anciennes données est nécessaire.


### Mesure locale et correctif du 16.11.2026

La collecte locale compte désormais **5 046 offres actives dans les 26 cantons**. Le premier
passage a duré **3 h 14**, dont 87 min sur EY avant une déconnexion. Le pré-filtre
SuccessFactors téléchargeait trop d'annonces étrangères à cause des codes postaux à quatre
chiffres ; un code postal seul n'est maintenant admis que sur le board suisse Hirslanden.
La reprise d'EY avec le correctif a réussi en **2 min 17** (123 offres).

Déployer la version incluant ce correctif. Le cycle complet corrigé n'a pas été remesuré,
et les limites de mémoire restent à valider sur le VPS : conserver la surveillance du délai
systemd de 3 h et du rapport qualité. Le nombre local ne prouve pas le nombre actuellement
servi par le VPS. [Bilan détaillé](../docs/crawl-suisse-2026-11-15.md).


## Mise à jour du 17.11.2026 : familles de métier (onboarding de DoxAI)

Purement additif : `GET /jobs` et `POST /recommend` acceptent un filtre facultatif `families`
(libellés exacts de `family`, OU entre eux, ET avec les autres filtres) ; `/jobs` gagne la
facette `facets.families`. Deux routes nouvelles, sous le même jeton : `GET /families` (les 15
familles) et `POST /classify` (`{"titles": [...]}` → leurs familles, sans modèle). Sans
`families`, les réponses sont identiques à avant, classement de `/recommend` compris (tests sur
les 13 fixtures). Aucune migration, aucune dépendance, ni le fichier Compose, ni le timer, ni
la collecte ne changent : seul le conteneur `job-rec-ai` redémarre (il sert le staging comme la
production de DoxAI ; quelques secondes, l'index se recharge au démarrage).

```bash
cd /opt/job-rec-ai
systemctl is-active job-rec-ai-crawl            # « inactive » : pas pendant la collecte
grep '^JOB_REC_TAG=' .env                       # noter l'ancien tag (retour arrière)
sed -i 's/^JOB_REC_TAG=.*/JOB_REC_TAG=<sha>/' .env
docker compose pull api && docker compose up -d api     # recrée le seul conteneur job-rec-ai
docker exec cv-app wget -qO- http://job-rec-ai:8000/health

# Vérifier (le jeton est lu dans .env, jamais affiché)
set -a; . /opt/job-rec-ai/.env; set +a
H="Authorization: Bearer $JOB_REC_TOKEN"
docker exec cv-app wget -qO- --header "$H" http://job-rec-ai:8000/families
docker exec cv-app wget -qO- --header "$H" \
  "http://job-rec-ai:8000/jobs?families=Informatique%20%26%20Tech&per_page=2"
docker exec cv-app wget -qO- --header "$H" --header "Content-Type: application/json" \
  --post-data '{"titles": ["Comptable", "Développeur full-stack"]}' \
  http://job-rec-ai:8000/classify
```

Retour arrière : remettre l'ancien `JOB_REC_TAG` et `docker compose up -d api`. Rien à défaire
dans la base. L'ancienne version ignore `families` sans erreur (sur `/jobs` comme sur
`/recommend`) : elle renverrait toutes les familles ; `/families` et `/classify` y répondent
`404`, et `facets.families` manque.

## Mise à jour du 20.11.2026 : langue des annonces

`language` de `/jobs` et `/jobs/{id}` était faux pour beaucoup d'annonces (Coop « Verkäufer:in
Food » → `en`). La base gagne une colonne `jobs.declared_language` (`ALTER TABLE … ADD COLUMN
IF NOT EXISTS`, ajoutée par le premier processus qui ouvre la base en écriture) ; le contrat
de l'API ne change pas. Ni le fichier Compose, ni les services, ni le timer ne changent.

```bash
cd /opt/job-rec-ai
# 1. L'image du commit de main qui contient la correction
grep '^JOB_REC_TAG=' .env                       # noter l'ancien tag (retour arrière)
sed -i 's/^JOB_REC_TAG=.*/JOB_REC_TAG=<sha>/' .env
docker compose pull api && docker compose up -d api     # recrée le seul conteneur job-rec-ai
docker exec cv-app wget -qO- http://job-rec-ai:8000/health

# 2. Recalculer la langue des offres en base, depuis data/raw (sans réseau, ~1-2 min ; pas
#    pendant la collecte de 03:17 UTC, qui verrouille la base). D'abord le décompte, puis
#    l'écriture. Sinon, la collecte suivante corrige d'elle-même les offres actives.
systemctl is-active job-rec-ai-crawl            # « inactive » : la voie est libre
docker compose --profile crawl run --rm crawl job-rec-ai backfill-language --dry-run
docker compose --profile crawl run --rm crawl job-rec-ai backfill-language
docker compose --profile crawl run --rm crawl job-rec-ai backfill-language --dry-run  # « 0 »

# 3. Vérifier (l'API relit la base au plus 5 min après)
set -a; . /opt/job-rec-ai/.env; set +a
docker exec cv-app wget -qO- --header "Authorization: Bearer $JOB_REC_TOKEN" \
  "http://job-rec-ai:8000/jobs?q=Verk%C3%A4ufer&per_page=3"
```

Retour arrière : remettre l'ancien `JOB_REC_TAG` et `docker compose up -d api`. L'ancienne
version ignore la colonne ajoutée et sert les langues recalculées telles quelles (elle ne les
réécrit qu'à sa prochaine collecte, avec l'ancienne règle).
