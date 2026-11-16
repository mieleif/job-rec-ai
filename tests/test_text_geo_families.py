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
    ("Vevey", "VD"), ("Zürich", "ZH"), ("Basel / Kaiseraugst", "BS"),
    ("Geneva, IL, United States", None), ("Annemasse, France", None), ("", None),
    # multi-sites réels (Proton, Logitech) : la Suisse citée l'emporte sur le pays étranger
    ("Geneva, Switzerland, Paris, France", "GE"),
    ("Lausanne, Switzerland / London, United Kingdom / Cork, Ireland", "VD"),
    # tirets et espaces équivalents (URL SuccessFactors : « Le-Grand-Saconnex-Stagiaire… »)
    ("Le Grand Saconnex", "GE"), ("Le Grand-Saconnex", "GE"), ("Plan les Ouates", "GE"),
    # veto jugé lieu par lieu : la Suisse d'un segment ne blanchit pas l'homonyme d'un autre
    ("Geneva, IL, United States / Zurich, Switzerland", "ZH"),
    ("Geneva, New York, USA; Lausanne, Switzerland", "VD"),
    # le reste de la Romandie (04.11.2026)
    ("Neuchâtel", "NE"), ("La Chaux-de-Fonds, CH", "NE"), ("Bulle (FR)", "FR"),
    ("Sion", "VS"), ("Delémont", "JU"), ("Biel/Bienne", "BE"),
    # Toute la Suisse : Haut-Valais, Singine et Seeland inclus
    ("Zermatt, CH-3920", "VS"), ("Visp, Switzerland", "VS"), ("Brig VS, Wallis", "VS"),
    ("Zermatt (VS)", "VS"), ("Murten, Freiburg, Schweiz", "FR"),
    ("Guin - Düdingen, Frei", "FR"), ("Tafers, Switzerland", "FR"),
    ("Grenchen, CH-2545", "SO"), ("Site, CH-1712 Taf", "FR"), ("Bureau, CH-2560 Nida", "BE"),
    ("Sierre / Visp", "VS"), ("Fribourg, CH-1700", "FR"),
    ("Bern", "BE"),
    # codes de pays et homonymes : « FR » et « BE » nus ne sont pas des cantons
    ("Paris, FR", None), ("Bruxelles, BE", None), ("Freiburg, Germany", None),
    ("Freiburg im Breisgau", None), ("Freiburg, DE", None), ("Neuenburg am Rhein", None),
    # homonymes VD / NE non listés : le nom seul ne permet pas de trancher
    ("Colombier", None), ("Corcelles-Cormondrèche", "NE"),
    # NPA quand aucun nom ne parle : ville tronquée par l'ATS
    ("Hirslanden Clinique Cecil, CH-1003 Laus", "VD"), ("Clinique, 1870 Mont, Switzerland", "VS"),
    ("Klinik, CH-8032 Zuri", "ZH"), ("Bureau 12.1234", None),
    # Moutier est jurassienne depuis le 01.01.2026 : le répertoire officiel le sait
    ("Site, CH-2740 Mout", "JU"), ("Moutier", "JU"),
    # sans indice suisse, un code postal à 4 chiffres ne prouve rien
    ("1000 Bruxelles", None), ("Mediclinic Morningside, 2196 Sand", None),
])
def test_canton_of(location, canton):
    assert canton_of(location) == canton


@pytest.mark.parametrize("location, canton", [
    # tous les NPA du répertoire officiel, pas seulement ceux de Romandie
    ("Site, CH-8001", "ZH"), ("Basel, CH, 4051", "BS"), ("Site, CH-6500", "TI"),
    ("Spital, 7000 Chur, Schweiz", "GR"), ("Site, CH-9999", None),  # NPA inexistant
    # une localité absente de la liste manuelle, seule dans son morceau du lieu
    ("CH - Ittigen", "BE"), ("Spital, Wetzikon ZH", "ZH"), ("3063 Ittigen", "BE"),
    ("Stein AG", "AG"), ("CH - Stein", None),  # Stein AG, AR et SG : ambigu
    # …mais pas un mot dans une phrase : « Rue » et « Sur » sont des localités
    ("Rue du Rhône 8", None), ("Sur site", None),
])
def test_repertoire_officiel(location, canton):
    assert canton_of(location) == canton


@pytest.mark.parametrize("location", [
    # homonymes étrangers des communes alémaniques : pays, région ou État nommés
    "Emmen, Netherlands", "Cham, Bavaria", "Baden, Austria", "Baden-Baden",
    "Lucerne, CA", "New Bern, NC", "Berne, Indiana", "Vaduz, Liechtenstein",
    # vus dans la collecte (EY, Accor)
    "Freiburg i. Br., 79098 BW", "Freiburg i.Br.", "Zürichstrasse 1, 78462 Konstanz",
    "Palma de Mallorca, 07010 Bale",
    # villes frontalières écrites avec leur voisine suisse
    "Saint-Louis (Bâle)", "Lörrach (bei Basel)",
    # « Ch. » est un chemin, pas la Suisse
    "Ch. des Mines 2, Paris",
])
def test_homonymes_etrangers(location):
    from job_rec_ai.geo import is_target
    assert canton_of(location) is None and not is_target(location)


@pytest.mark.parametrize("location, canton", [
    ("Crans-Montana", "VS"),  # « Montana » n'est pas un veto
    ("Neuchâtel, NE", "NE"), ("Herisau, AR", "AR"),  # codes de canton = codes d'États
    ("Lausanne, Switzerland / Emmen, Netherlands", "VD"),
    # État de Genève : numéro de rue collé au NPA, pas un code postal étranger
    ("Rue David-Dufour 51205 Genève", "GE"),
])
def test_veto_sans_faux_positif(location, canton):
    assert canton_of(location) == canton


def test_repertoire_construit_sans_ambiguite():
    from job_rec_ai.localities import build

    def row(name, npa, commune, canton, share="100 %"):
        return {"Ortschaftsname": name, "PLZ4": npa, "Gemeindename": commune,
                "Kantonskürzel": canton, "Adressenanteil": share}

    table = build([
        row("Stein AG", "4332", "Stein (AG)", "AG"), row("Stein AR", "9063", "Stein (AR)", "AR"),
        row("Versoix", "1290", "Versoix", "GE", "60 %"),
        row("Chavannes-des-Bois", "1290", "Chavannes-des-Bois", "VD", "40 %"),
        row("Lausanne 25", "1000", "Lausanne", "VD"), row("Vaduz", "9490", "Vaduz", "FL"),
    ])
    assert ("name", "stein ag", "AG") in table and ("name", "stein ar", "AR") in table
    assert not any(key == "stein" for _, key, _ in table)  # forme courte ambiguë
    assert not any(kind == "npa" and key == "1290" for kind, key, _ in table)  # partagé
    assert ("name", "lausanne", "VD") in table and ("npa", "1000", "VD") in table
    assert not any(canton == "FL" for *_, canton in table)  # Liechtenstein écarté


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
    ("Lehrstelle als Chemie- und Pharmatechnologe EFZ", "Stage / Apprentissage"),
    # programmes de relève : « cadre » n'y veut pas dire senior
    ("Futur Cadre Junior (H/F)", "Junior"),
    ("Aspirant·e (Relève Futur·e cadre) / Région de la Gruyère", "Junior"),
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
    ("Au moins 1 an d'expérience en comptabilité", 1),
    ("Une année d'expérience dans la vente", 1),
    # l'histoire de la maison n'est pas une exigence : on prend la mention suivante
    ("Fort de 25 ans d'expérience, notre cabinet recrute. Vous avez 2 ans d'expérience.", 2),
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


def test_seniorite_par_le_niveau_de_l_ats():
    # Coop : « Cadre » dans le champ Poste veut dire encadrement ; « Collaborateur » ne dit rien
    assert classify("Gérant·e de magasin", level="Cadre").seniority == "Senior / Lead"
    assert classify("Vendeur·se", level="Collaborateur").seniority == "Non précisé"


@pytest.mark.parametrize("title, expected", [
    ("Comptable 80-100%", (80, 100)), ("Assistant·e 50 %", (50, 50)),
    ("Infirmier 60 – 80 %", (60, 80)), ("Data Engineer", (None, None)),
])
def test_taux_activite(title, expected):
    assert workload(title) == expected


@pytest.mark.parametrize("country, expected", [
    ("CH", True), ("CHE", True), ("Switzerland", True), ("Schweiz", True), ("Suisse", True),
    ("ZA", False), ("Deutschland", False), (None, False),
])
def test_is_switzerland(country, expected):
    from job_rec_ai.geo import is_switzerland
    assert is_switzerland(country) == expected


@pytest.mark.parametrize("place, expected", [
    ("Aarau", "AG"), ("Appenzell", "AI"), ("Herisau", "AR"), ("Bern", "BE"),
    ("Allschwil", "BL"), ("Basel", "BS"), ("Fribourg", "FR"), ("Genève", "GE"),
    ("Glarus", "GL"), ("Chur", "GR"), ("Delémont", "JU"), ("Luzern", "LU"),
    ("Neuchâtel", "NE"), ("Stans", "NW"), ("Alpnach", "OW"), ("St. Gallen", "SG"),
    ("Schaffhausen", "SH"), ("Solothurn", "SO"), ("Schwyz", "SZ"), ("Frauenfeld", "TG"),
    ("Lugano", "TI"), ("Altdorf", "UR"), ("Lausanne", "VD"), ("Visp", "VS"),
    ("Zug", "ZG"), ("Zürich", "ZH"),
    ("Site, Basel-Landschaft", "BL"), ("Site, Appenzell Ausserrhoden", "AR"),
    ("Bellinzona, Ticino", "TI"), ("Site, TI, CH", "TI"),
])
def test_tous_les_cantons(place, expected):
    from job_rec_ai.geo import is_target
    assert is_target(place)
    assert canton_of(place) == expected
    assert canton_of(f"Site ({expected})") == expected


@pytest.mark.parametrize("place, expected", [
    ("Switzerland", True), ("Remote, Schweiz", True), ("Suisse", True),
    ("Comune sconosciuto, Svizzera", True), ("Site inconnu, CH", True),
    ("Site inconnu, CH-6500", True), ("Unknown, CHE", True),
    ("Remote", False), ("Paris, FR", False), ("Bruxelles, BE", False),
    ("Zurich, Germany", False), ("Geneva, IL, United States", False),
    ("Switzerlandish", False), (None, False),
])
def test_perimetre_suisse_sans_canton_obligatoire(place, expected):
    from job_rec_ai.geo import is_target
    assert is_target(place) is expected
