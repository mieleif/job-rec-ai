#!/usr/bin/env bash
# Met l'API du VPS sur l'image ghcr.io/mieleif/job-rec-ai:$TAG, avec retour arrière automatique.
#
# Lancé par le workflow Deploy (.github/workflows/deploy.yml), sur le VPS, par SSH :
#   ssh user@vps "TAG=<sha> bash -s" < deploy/deploy.sh
# À la main, même commande depuis un clone du dépôt.
#
# Étapes : refuse si une collecte tourne (même règle que la procédure manuelle), suspend le
# timer, écrit le tag dans .env, tire l'image, recrée le seul conteneur job-rec-ai, vérifie
# /health puis /status. Si la vérification échoue : remet l'ancien tag et recrée l'API.
# La collecte suivante (timer de 03:17 UTC) prend la même image, lue dans le même .env.
set -euo pipefail

if [[ -z "${TAG:-}" ]]; then
  echo "TAG manquant : le SHA complet d'un commit de main" >&2
  exit 2
fi
[[ "$TAG" =~ ^[0-9a-f]{40}$ ]] || { echo "TAG doit être un SHA complet : $TAG" >&2; exit 2; }
DIR=${JOB_REC_DIR:-/opt/job-rec-ai}
cd "$DIR"

previous=$(sed -n 's/^JOB_REC_TAG=//p' .env)
echo "Version en place : ${previous:-latest} ; demandée : $TAG"
if [[ "$previous" == "$TAG" ]] && docker ps --format '{{.Image}}' | grep -qx "ghcr.io/mieleif/job-rec-ai:$TAG"; then
  echo "Déjà déployée : rien à faire."
  exit 0
fi
if systemctl is-active --quiet job-rec-ai-crawl; then
  echo "Une collecte tourne (de 03:17 UTC à ~06:30) : relancer le déploiement après sa fin." >&2
  exit 75
fi

set_tag() {
  if grep -q '^JOB_REC_TAG=' .env; then
    sed -i "s/^JOB_REC_TAG=.*/JOB_REC_TAG=$1/" .env
  else
    printf 'JOB_REC_TAG=%s\n' "$1" >> .env
  fi
}

healthy() {
  local token
  token=$(sed -n 's/^JOB_REC_TOKEN=//p' .env)
  for _ in $(seq 1 30); do
    # /health : le serveur répond ; /status : le jeton est accepté et la base est lue
    if docker exec cv-app wget -qO- http://job-rec-ai:8000/health 2>/dev/null | grep -q '"ok"' \
      && docker exec cv-app wget -qO- --header "Authorization: Bearer $token" \
           http://job-rec-ai:8000/status 2>/dev/null; then
      echo
      return 0
    fi
    sleep 2
  done
  return 1
}

sudo systemctl stop job-rec-ai-crawl.timer
trap 'sudo systemctl start job-rec-ai-crawl.timer' EXIT

set_tag "$TAG"
docker compose pull -q api
docker compose up -d api
if healthy; then
  echo "Déployée : $TAG"
  exit 0
fi

echo "Vérification échouée : retour à ${previous:-latest}" >&2
set_tag "${previous:-latest}"
docker compose up -d api
healthy || echo "L'ancienne version ne répond pas non plus : intervenir à la main." >&2
exit 1
