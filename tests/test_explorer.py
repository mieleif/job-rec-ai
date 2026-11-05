"""L'explorateur : export des offres actives et page HTML autonome."""

import json
import re
from datetime import date, datetime

from job_rec_ai import explorer, pipeline, storage
from job_rec_ai.models import Job


def _job(n, title, description="Pipelines de données en Python."):
    return Job(title=title, company="Acme", url=f"https://acme.example/jobs/{n}",
               location="Genève", description=description, source="workday")


def test_offres_actives_pour_l_explorateur():
    con = storage.connect(":memory:")
    rows = [pipeline.enrich(_job(1, "Data Engineer", "x" * 1000)),
            pipeline.enrich(_job(2, "Comptable"))]
    storage.upsert_jobs(con, rows, datetime(2026, 11, 1))
    con.execute("UPDATE jobs SET active = FALSE WHERE url LIKE '%/2'")
    (job,) = storage.active_jobs(con)  # l'offre expirée n'y est pas
    assert job["title"] == "Data Engineer" and job["canton"] == "GE"
    assert len(job["excerpt"]) == storage.EXCERPT  # un extrait, pas la description entière
    assert job["first_seen"] == "2026-11-01" and job["publisher_type"] == "employeur"


def test_page_autonome_et_sure():
    jobs = [{"title": "Analyste </script><script>alert(1)</script>", "company": "Acme",
             "canton": "GE", "url": "https://acme.example/1"},
            {"title": "Juriste", "company": "Beta", "canton": "VD", "url": "https://b.example/2"}]
    page = explorer.render(jobs, today=date(2026, 11, 5))
    assert "2 offres actives · 2 employeurs · 2 cantons · mise à jour le 05.11.2026" in page
    # un titre ne peut pas refermer la balise qui porte les données
    data = re.search(r'<script id="data" type="application/json">(.*?)</script>', page, re.S)
    assert json.loads(data.group(1))[0]["title"].startswith("Analyste </script>")
    assert 'new Date("2026-11-05T00:00:00")' in page
