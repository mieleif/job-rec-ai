import pytest

from job_rec_ai.families import classify, workload, years_of_experience
from job_rec_ai.geo import canton_of
from job_rec_ai.text import clean_html, detect_language


def test_clean_html_greenhouse_double_echappement():
    assert clean_html("&lt;p&gt;Python &amp;amp; SQL&lt;/p&gt;") == "Python & SQL"


def test_clean_html_separe_les_blocs():
    assert clean_html("<ul><li>Python</li><li>SQL</li></ul>") == "Python SQL"


def test_detect_language_allemand_est_other():
    de = "Wir suchen einen Data Engineer für unser Team in Zürich mit Erfahrung in der Cloud."
    assert detect_language(de) == "other"


@pytest.mark.parametrize("location, canton", [
    ("Genève", "GE"), ("Geneva, Switzerland", "GE"), ("Meyrin (GE)", "GE"),
    ("Plan-les-Ouates", "GE"), ("Lausanne, VD", "VD"), ("Le Brassus", "VD"),
    ("Vevey", "VD"), ("Zürich", None), ("Basel / Kaiseraugst", None),
    ("Geneva, IL, United States", None), ("Annemasse, France", None), ("", None),
    # multi-sites réels (Proton, Logitech) : la Suisse citée l'emporte sur le pays étranger
    ("Geneva, Switzerland, Paris, France", "GE"),
    ("Lausanne, Switzerland / London, United Kingdom / Cork, Ireland", "VD"),
    # tirets et espaces équivalents (URL SuccessFactors : « Le-Grand-Saconnex-Stagiaire… »)
    ("Le Grand Saconnex", "GE"), ("Le Grand-Saconnex", "GE"), ("Plan les Ouates", "GE"),
    # veto jugé lieu par lieu : la Suisse d'un segment ne blanchit pas l'homonyme d'un autre
    ("Geneva, IL, United States / Zurich, Switzerland", None),
    ("Geneva, New York, USA; Lausanne, Switzerland", "VD"),
])
def test_canton_of(location, canton):
    assert canton_of(location) == canton


@pytest.mark.parametrize("title, family", [
    ("Data Engineer", "Data & IA"),
    ("Senior Software Engineer - Backend", "Informatique & Tech"),
    ("Infirmier·ère en soins intensifs 80-100%", "Santé & Soins"),
    ("Compliance Officer KYC", "Juridique & Compliance"),
    ("Relationship Manager Private Banking", "Banque & Gestion de fortune"),
    ("Comptable fournisseurs", "Finance & Comptabilité"),
    ("HR Business Partner", "Ressources humaines"),
    ("Supply Chain Planner", "Supply chain & Achats"),
    ("Polymécanicien CFC", "Ingénierie & Production"),
    ("Horloger rhabilleur", "Ingénierie & Production"),
    ("Assistante de direction", "Administration & Assistanat"),
    ("Chargé·e de mission", "Autre"),
])
def test_familles(title, family):
    assert classify(title).family == family


def test_classement_explique_sa_decision():
    c = classify("Supply Chain Planner")
    assert c.family_keyword == "supply chain"  # le mot-clé le plus long gagne


@pytest.mark.parametrize("title, seniority", [
    ("Stagiaire Marketing", "Stage / Apprentissage"),
    ("Apprenti·e employé·e de commerce", "Stage / Apprentissage"),
    ("Head of Data", "Direction"),
    ("Senior Accountant", "Senior / Lead"),
    ("Junior Analyst", "Junior"),
    ("Électricien CFC", "Non précisé"),  # CFC = diplôme obtenu, pas un apprentissage
    ("Postdoc Position in Quantitative Finance", "Junior"),
    ("Assistant(e) Audit - Genève (Graduate)", "Junior"),
])
def test_seniorite(title, seniority):
    assert classify(title).seniority == seniority


@pytest.mark.parametrize("description, years", [
    ("You have 5+ years of experience in treasury.", 5),
    ("3-5 years’ experience in EHS", 4),
    ("2 to 5 years of experience", 3.5),
    ("Au moins 3 ans d'expérience dans un poste similaire", 3),
    ("A minimum of five years of relevant professional experience", 5),
    ("Mindestens 4 Jahre Berufserfahrung", 4),
    ("Founded 150 years ago, our experience is unique", None),
    ("Rejoignez une équipe de 12 personnes.", None),
])
def test_annees_d_experience(description, years):
    assert years_of_experience(description) == years


def test_seniorite_par_la_description():
    # Le titre ne dit rien : la description tranche ; le titre prime quand il est explicite
    assert classify("Treasury Officer", "10 years of experience").seniority == "Senior / Lead"
    assert classify("Data Architect", "3 years of experience").seniority == "Confirmé·e"
    assert classify("Analyst", "1 year of experience").seniority == "Junior"
    assert classify("Senior Analyst", "1 year of experience").seniority == "Senior / Lead"
    assert classify("Comptable", "Poste à 80 %").seniority == "Non précisé"


@pytest.mark.parametrize("title, expected", [
    ("Comptable 80-100%", (80, 100)), ("Assistant·e 50 %", (50, 50)),
    ("Infirmier 60 – 80 %", (60, 80)), ("Data Engineer", (None, None)),
])
def test_taux_activite(title, expected):
    assert workload(title) == expected
