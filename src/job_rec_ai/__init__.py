from importlib.metadata import version

# Source unique de vérité : la version déclarée dans pyproject.toml
__version__ = version("job-rec-ai")


def main() -> None:
    # Import tardif : `import job_rec_ai` reste léger (pas de DuckDB ni httpx chargés)
    from job_rec_ai.cli import main as cli_main

    cli_main()
