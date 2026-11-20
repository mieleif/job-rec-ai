"""La langue d'une annonce : le texte tranche quand il est clair, la langue déclarée par l'ATS
sinon ; et le recalcul des offres déjà en base (`backfill-language`)."""

import itertools
from datetime import datetime

import pytest

from job_rec_ai import catalog, cli, pipeline, storage
from job_rec_ai.models import Job
from job_rec_ai.text import _MARKERS, guess_language, resolve_language

# Une annonce Coop typique, dans sa version longue (souvent, Coop n'écrit que le titre)
COOP_DE = ("Verkäufer:in Food. Du bist eine motivierte Person und hast Freude am Kontakt mit "
           "unserer Kundschaft. Wir bieten dir eine abwechslungsreiche Stelle in einem "
           "dynamischen Team und die Möglichkeit, dich weiterzuentwickeln. Bei uns sind "
           "Weiterbildungen und attraktive Anstellungsbedingungen selbstverständlich.")
EN = ("We are looking for a Data Engineer to join our team in Geneva. You will build and "
      "maintain the data platform with Python and SQL, and work closely with our analysts "
      "to deliver reliable pipelines. This is a full-time role based in our office.")
IT = ("Siamo alla ricerca di un collaboratore per il nostro team di Lugano. Il candidato "
      "ideale ha esperienza nella vendita e una buona conoscenza del tedesco, che sono "
      "requisiti indispensabili per questo ruolo.")
# Le cas réel : Coop n'écrit que le titre ; l'ancienne règle comptait « in » pour l'anglais
COOP_TITLE = "Verkäufer:in Food Verkäufer:in Food"


def test_les_mots_outils_n_appartiennent_qu_a_une_langue():
    for (a, wa), (b, wb) in itertools.combinations(_MARKERS.items(), 2):
        assert not wa & wb, f"{a}/{b} : {wa & wb}"


def test_annonce_allemande_etiquetee_en_par_l_ats():
    """Le texte clair l'emporte sur une langue déclarée fausse (EY, Nestlé : « en-US »)."""
    assert resolve_language("en", COOP_DE) == "de"
    assert resolve_language("en-US", COOP_DE) == "de"


def test_une_vraie_annonce_anglaise_reste_en():
    assert resolve_language(None, EN) == "en"
    assert resolve_language("en", EN) == "en"
    assert resolve_language("fr-FR", EN) == "en"  # EPFL : « fr-FR » sur un postdoc en anglais


def test_titre_seul_garde_la_langue_declaree():
    assert guess_language(COOP_TITLE) is None  # plus jamais « en » à cause de « in »
    assert resolve_language("de-DE", COOP_TITLE) == "de"
    assert resolve_language(None, COOP_TITLE) == "other"


def test_texte_ambigu_garde_la_langue_declaree():
    """Moitié français, moitié anglais : ni l'un ni l'autre ne domine, l'ATS tranche."""
    bilingual = ("Nous recherchons un ingénieur pour notre équipe et vous serez au cœur des "
                 "projets. We are looking for an engineer to join our team and you will lead.")
    assert guess_language(bilingual) is None
    assert resolve_language("fr", bilingual) == "fr"
    assert resolve_language("en_GB", bilingual) == "en"


def test_l_italien_est_reconnu():
    assert resolve_language(None, IT) == "it"
    assert catalog.language_code("other", IT) == "it"  # offres déjà en base (fr/en/other)
    assert catalog.language_code("it-IT", "") == "it"


@pytest.mark.parametrize("declared", [None, "EN", "xx", ""])
def test_langue_declaree_inconnue_ou_absente(declared):
    assert resolve_language(declared, "Python SQL") == ("en" if declared == "EN" else "other")


def test_enrich_garde_la_declaration_et_retient_le_texte():
    job = Job(title="Verkäufer:in Food", company="Coop", url="https://jobs.coop.ch/job/1/",
              location="Basel", description=COOP_DE, language="en-US",
              source="successfactors")
    row = pipeline.enrich(job)
    assert (row["language"], row["declared_language"]) == ("de", "en-US")


# --- backfill-language -------------------------------------------------------------------

def _payload():
    """Une archive Greenhouse : l'offre 1 déclare l'allemand, la 2 rien."""
    return {"ats": "greenhouse", "company": "Coop", "board": "coop",
            "fetched_at": "2026-11-15T06:00:00+00:00",
            "postings": [{"id": i, "title": "Verkäufer:in Food", "location": {"name": "Basel"},
                          "absolute_url": f"https://job-boards.greenhouse.io/coop/jobs/{i}",
                          "language": lang}
                         for i, lang in ((1, "de"), (2, None))]}


@pytest.fixture
def stale(tmp_path, monkeypatch):
    """Une base « d'avant » : 3 offres étiquetées par l'ancienne règle, et data/raw/."""
    monkeypatch.chdir(tmp_path)  # data/raw et data/jobs.duckdb : les chemins par défaut
    pipeline.save_raw(_payload(), pipeline.RAW_DIR)
    con = storage.connect(tmp_path / "data" / "jobs.duckdb")
    jobs = [("https://job-boards.greenhouse.io/coop/jobs/1", "Verkäufer:in Food", ""),
            ("https://job-boards.greenhouse.io/coop/jobs/2", "Verkäufer:in Food", COOP_DE),
            ("https://job-boards.greenhouse.io/coop/jobs/3", "Data Engineer", EN)]
    rows = [{**pipeline.enrich(Job(title=title, company="Coop", url=url, location="Basel",
                                   description=text, source="greenhouse")),
             "language": "en", "declared_language": None}  # l'ancienne règle : « en »
            for url, title, text in jobs]
    storage.upsert_jobs(con, rows, datetime(2026, 11, 15))
    yield con
    con.close()


def _languages(con):
    return con.execute("SELECT language, declared_language FROM jobs ORDER BY url").fetchall()


def test_backfill_dry_run_compte_sans_ecrire(stale):
    before = _languages(stale)
    result = pipeline.backfill_language(stale, dry_run=True)
    assert (result.archives, result.jobs) == (1, 3)
    assert result.changes == {("greenhouse", "en", "de"): 2}  # l'offre 3 était juste
    assert _languages(stale) == before


def test_backfill_ecrit_et_se_rejoue_sans_effet(stale):
    pipeline.backfill_language(stale)
    assert _languages(stale) == [("de", "de"), ("de", None), ("en", None)]
    assert pipeline.backfill_language(stale).changes == {}  # idempotent


def test_backfill_en_ligne_de_commande(stale, capsys):
    stale.close()  # la commande ouvre la base elle-même
    cli.main(["backfill-language", "--dry-run"])
    out = capsys.readouterr().out
    assert "3 offres, 1 archives de data/raw/ relues : 2 langues changeraient" in out
    assert "greenhouse" in out and "en → de" in out and "--dry-run" in out
    con = storage.connect("data/jobs.duckdb")
    assert [lang for lang, _ in _languages(con)] == ["en", "en", "en"]  # rien d'écrit
    con.close()
