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
  collecte dure **environ 75 minutes** (Coop seul : 10 à 15 min, à cause des pauses entre
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
