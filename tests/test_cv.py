from job_rec_ai.cv import clean, read_cv
from job_rec_ai.text import tokenize


def test_clean_recolle_les_cesures_et_retire_icones_et_puces():
    raw = ("Expérience en con-\nception d'un SaaS\n"
           " app.example.ch |  in/jdupont\n"
           "■ Python, SQL\n- Docker\n")
    assert clean(raw) == ("Expérience en conception d'un SaaS\n"
                          "app.example.ch | in/jdupont\n"
                          "Python, SQL\n- Docker")


def test_read_cv_texte_brut(tmp_path):
    path = tmp_path / "cv.md"
    path.write_text("Data   Engineer\n\n■ dbt, Air-\nflow\n", encoding="utf-8")
    assert read_cv(path) == "Data Engineer\ndbt, Airflow"


def test_tokenize():
    assert tokenize("Développeur·se C++ / C#, l'IA générative") == [
        "developpeur", "se", "c++", "c#", "ia", "generative"]
