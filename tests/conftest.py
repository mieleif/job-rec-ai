import sys
from pathlib import Path

import pytest

from job_rec_ai.http import PoliteClient

sys.path.insert(0, str(Path(__file__).parent))  # pour importer fake_ats

from fake_ats import transport  # noqa: E402


@pytest.fixture
def sleeps():
    """Les attentes demandées par le client, enregistrées au lieu d'être subies."""
    return []


@pytest.fixture
def client(sleeps):
    with PoliteClient(delay=1.0, transport=transport(), sleep=sleeps.append) as c:
        yield c


@pytest.fixture(autouse=True)
def small_workday_pages(monkeypatch):
    """Pages de 2 offres : avec 3 offres, la pagination est forcément exercée."""
    monkeypatch.setattr("job_rec_ai.connectors.workday.PAGE_SIZE", 2)
