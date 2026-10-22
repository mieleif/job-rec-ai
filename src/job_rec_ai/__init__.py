from importlib.metadata import version

# Source unique de vérité : la version déclarée dans pyproject.toml
__version__ = version("job-rec-ai")


def main() -> None:
    print("Hello from job-rec-ai!")
