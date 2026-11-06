# Déploiement sur le VPS de DoxAI : l'API et la collecte nocturne

job-rec-ai tourne sur le même VPS que DoxAI, en conteneurs, à côté de la pile `/opt/n8n-stack`
**sans la modifier** : c'est un projet Compose à part, dans `/opt/job-rec-ai`.

```
            réseau Docker n8n-stack_default (pas d'URL publique)
 cv-app-web ──── POST http://job-rec-ai:8000/recommend ────▶ job-rec-ai (API, BM25 en mémoire)
                                                                  │ lit (lecture seule)
 timer systemd 03:17 ──▶ docker compose run crawl ──écrit──▶ volume data : jobs.duckdb + raw/
```

- **Image** : `ghcr.io/mieleif/job-rec-ai:<sha>`, publiée par `.github/workflows/image.yml` à
  chaque push sur `main` (même principe que les images DoxAI : un tag immuable par commit).
- **API** : `GET /health`, `GET /status`, `POST /recommend` (voir `src/job_rec_ai/api.py` et
  [docs/integration-doxai.md](../docs/integration-doxai.md)). Joignable seulement depuis le
  réseau Docker de DoxAI, sous le nom `job-rec-ai`. Jeton partagé `JOB_REC_TOKEN`.
- **Collecte** : le même conteneur, commande `crawl`, lancée chaque nuit par un timer systemd.
  L'API relit la base quand le fichier a changé (au plus toutes les 5 minutes) ; pendant la
  collecte, la base est verrouillée en écriture et l'API sert l'index de la veille.
- **Mémoire** : API ≈ 150-250 Mo (plafond 384 Mo), collecte plafonnée à 768 Mo : le VPS a 4 Go
  partagés avec la production DoxAI.

## Installation (une fois, en SSH)

```bash
# 1. Le dossier du projet et ses deux fichiers
sudo mkdir -p /opt/job-rec-ai && sudo chown "$USER" /opt/job-rec-ai && cd /opt/job-rec-ai
for f in docker-compose.yml job-rec-ai-crawl.service job-rec-ai-crawl.timer; do
  curl -fsSLO "https://raw.githubusercontent.com/mieleif/job-rec-ai/main/deploy/$f"; done
printf 'JOB_REC_TOKEN=%s\nJOB_REC_TAG=latest\n' "$(openssl rand -hex 32)" > .env && chmod 600 .env

# 2. Vérifier le nom du réseau Docker de DoxAI (sinon : DOXAI_NETWORK=… dans .env)
docker network ls | grep n8n-stack

# 3. La base de départ : copier celle du PC (plus rapide qu'une première collecte)
#    depuis le PC : scp data/jobs.duckdb vps:/tmp/ puis, sur le VPS :
docker compose pull api
docker compose run --rm --no-deps -v /tmp:/import crawl sh -c 'cp /import/jobs.duckdb /srv/data/'

# 4. L'API, puis un essai depuis le conteneur web de DoxAI
docker compose up -d api
docker exec cv-app-web wget -qO- http://job-rec-ai:8000/health

# 5. Le timer de la collecte nocturne (unités systemd du système)
sudo cp job-rec-ai-crawl.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now job-rec-ai-crawl.timer
```

Côté DoxAI, ajouter à `/opt/n8n-stack/cv-app.env` (puis recréer `cv-app` avec les fichiers
Compose habituels, release override compris) :

```
JOB_REC_URL=http://job-rec-ai:8000
JOB_REC_TOKEN=<la même valeur que dans /opt/job-rec-ai/.env>
```

## Au quotidien

```bash
cd /opt/job-rec-ai
systemctl list-timers job-rec-ai-crawl.timer          # prochaine collecte
sudo systemctl start job-rec-ai-crawl                 # lancer une collecte maintenant
journalctl -u job-rec-ai-crawl -n 100                 # sortie de la dernière collecte
docker compose logs --tail 50 api                     # requêtes servies (jamais le texte des CV)
docker compose pull && docker compose up -d api       # mettre à jour (JOB_REC_TAG dans .env)
```

Données à sauvegarder : le volume `job-rec-ai_data` (`jobs.duckdb` et `raw/`). La base se
reconstruit à partir de `raw/` (`docker compose --profile crawl run --rm crawl job-rec-ai replay`).
