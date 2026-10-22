"""Checkpoints de la roadmap : un fichier de tests d'acceptation par étape.

Ils décrivent CE QUE le code doit faire, jamais COMMENT. Ils sont écrits à l'avance,
on ne les modifie pas pour les faire passer.
Lancer un checkpoint : uv run pytest checkpoints/test_m3_baseline.py -v
"""

import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


@pytest.fixture
def need():
    """need("job_rec_ai.koans", "cosine_similarity") importe ce qu'il faut, ou explique ce qui manque."""

    def _need(module: str, *names: str):
        try:
            mod = importlib.import_module(module)
        except ModuleNotFoundError as e:
            pytest.fail(f"module introuvable : {e.name} (requis : {module})", pytrace=False)
        missing = [n for n in names if not hasattr(mod, n)]
        if missing:
            pytest.fail(f"{module} n'expose pas encore : {', '.join(missing)}", pytrace=False)
        objs = [getattr(mod, n) for n in names]
        if not objs:
            return mod
        return objs[0] if len(objs) == 1 else objs

    return _need
