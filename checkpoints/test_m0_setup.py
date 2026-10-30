"""Checkpoint M0 : setup du projet."""

import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _pyproject() -> dict:
    path = ROOT / "pyproject.toml"
    assert path.exists(), "pyproject.toml introuvable : lance uv init"
    return tomllib.loads(path.read_text(encoding="utf-8"))


def test_python_moderne():
    """Tourner sur Python 3.12 ou plus récent (installé via uv)."""
    assert sys.version_info >= (3, 12), f"Python {sys.version.split()[0]} détecté : lance avec uv run pytest"


def test_pyproject_valide():
    """Avoir un pyproject.toml avec un nom de projet et une version de Python requise."""
    project = _pyproject().get("project", {})
    assert project.get("name"), "[project] name manquant"
    assert project.get("requires-python"), "[project] requires-python manquant"


def test_lockfile():
    """Avoir un uv.lock (les versions exactes de toutes les dépendances)."""
    assert (ROOT / "uv.lock").exists(), "uv.lock introuvable : lance uv sync ou uv add"


def test_package_importable(need):
    """Exposer un package job_rec_ai importable avec un __version__."""
    version = need("job_rec_ai", "__version__")
    assert isinstance(version, str) and version, "__version__ doit être une chaîne non vide"


def test_outils_de_dev():
    """Déclarer ruff et pytest comme dépendances de dev."""
    data = _pyproject()
    groups = data.get("dependency-groups", {})
    deps = " ".join(groups.get("dev", []) + data.get("tool", {}).get("uv", {}).get("dev-dependencies", []))
    assert "ruff" in deps, "ruff absent des dépendances de dev (uv add --dev ruff)"
    assert "pytest" in deps, "pytest absent des dépendances de dev (uv add --dev pytest)"


def test_ruff_configure():
    """Configurer ruff dans pyproject.toml ([tool.ruff])."""
    assert "ruff" in _pyproject().get("tool", {}), "section [tool.ruff] manquante"


def test_depot_git():
    """Être un dépôt git."""
    assert (ROOT / ".git").exists(), "pas de dossier .git : lance git init"


def test_secrets_ignores():
    """Ignorer .venv et .env dans .gitignore."""
    path = ROOT / ".gitignore"
    assert path.exists(), ".gitignore introuvable"
    text = path.read_text(encoding="utf-8")
    assert ".venv" in text and ".env" in text, ".venv et .env doivent figurer dans .gitignore"
