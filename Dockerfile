# Une image pour l'API de recommandation et pour la collecte nocturne (même code, deux commandes).
# Données hors de l'image : /srv/data est un volume (base DuckDB + réponses brutes data/raw/).
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1

WORKDIR /app
# Dépendances d'abord : cette couche ne se reconstruit que si uv.lock change
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev
# La liste des employeurs et les corrections de leurs domaines voyagent avec le code (le volume
# ne les masque pas) ; company_domains.csv est lu à côté de --companies
COPY data/companies.csv data/company_domains.csv /app/

RUN useradd --create-home --uid 1000 app && mkdir -p /srv/data && chown app /srv/data
USER app
# Chemins relatifs du code (data/jobs.duckdb, data/raw/) résolus dans le volume
WORKDIR /srv
ENV JOB_REC_DB=/srv/data/jobs.duckdb

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"
CMD ["uvicorn", "job_rec_ai.api:app", "--host", "0.0.0.0", "--port", "8000"]
