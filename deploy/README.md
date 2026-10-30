# Déploiement sur un VPS : la collecte nocturne

La collecte tourne **sur le VPS lui-même**, là où vit la base DuckDB, grâce à un timer
systemd (l'équivalent moderne de cron, présent sur Debian et Ubuntu).

Pourquoi un timer plutôt que cron :
- `Persistent=true` rattrape la collecte manquée si le VPS était éteint ;
- les sorties vont dans le journal (`journalctl`), avec horodatage et rotation automatique ;
- systemd ne lance jamais deux collectes en même temps.

## Installation (une fois, en SSH, avec ton utilisateur habituel : pas besoin de root)

```bash
# 1. uv, puis le code et ses dépendances (versions exactes de uv.lock)
curl -LsSf https://astral.sh/uv/install.sh | sh
git clone https://github.com/mieleif/job-rec-ai.git ~/job-rec-ai
cd ~/job-rec-ai && uv sync --frozen

# 2. Un premier essai à la main, sur une seule entreprise
uv run job-rec-ai crawl --company Richemont && uv run job-rec-ai quality

# 3. Le timer (unités systemd « utilisateur »)
mkdir -p ~/.config/systemd/user
cp deploy/job-rec-ai-crawl.{service,timer} ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now job-rec-ai-crawl.timer

# 4. Laisser tes unités tourner quand tu n'es pas connecté en SSH (sinon : rien la nuit)
sudo loginctl enable-linger "$USER"
```

## Au quotidien

```bash
systemctl --user list-timers                        # prochaine collecte prévue
systemctl --user start job-rec-ai-crawl             # lancer une collecte maintenant
journalctl --user -u job-rec-ai-crawl -n 100        # sortie de la dernière collecte
cd ~/job-rec-ai && git pull && uv sync --frozen     # mettre à jour le code
```

La base est dans `~/job-rec-ai/data/jobs.duckdb` et les réponses brutes dans
`~/job-rec-ai/data/raw/`. Ce sont les seules données à sauvegarder : la base se
reconstruit à partir de `data/raw/` (`uv run job-rec-ai replay`).
