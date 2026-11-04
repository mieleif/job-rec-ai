"""Classement par règles : famille de métier, séniorité et taux d'activité, à partir du titre
(et, pour la séniorité, des années d'expérience demandées dans la description).

Pourquoi des règles plutôt qu'un modèle ? Elles sont gratuites, instantanées, et surtout
explicables : chaque décision renvoie le mot-clé qui l'a déclenchée. Leur défaut, c'est
d'être fragiles (synonymes oubliés, titres ambigus). On mesurera leur taux d'erreur sur un
échantillon annoté, et c'est ce chiffre qui dira s'il faut passer à un LLM (M5).

L'ordre des familles compte : la première qui correspond gagne. Les familles les plus
spécifiques passent donc avant les plus génériques (« Data Engineer » doit tomber dans
Data & IA, pas dans Ingénierie).
"""

import re
from dataclasses import dataclass

from job_rec_ai.text import compile_keywords, first_match, normalize

OTHER = "Autre"

# (famille, mots-clés FR/EN/DE) ; les mots-clés sont comparés au titre normalisé
# (minuscules, sans accents), en mots entiers : « it » ne doit pas matcher « audit ».
FAMILY_RULES: list[tuple[str, list[str]]] = [
    ("Data & IA", [
        "data", "donnees", "machine learning", "ml", "ai", "ia", "intelligence artificielle",
        "artificial intelligence", "bi", "business intelligence", "analytics", "analyst data",
        "statisticien", "statistician", "llm", "nlp", "deep learning",
    ]),
    ("Informatique & Tech", [
        "software", "developer", "developpeur", "developpeuse", "devops", "cloud", "it",
        "informatique", "informaticien", "informaticienne", "cyber", "security engineer",
        "network", "reseau", "sap", "salesforce", "frontend", "backend", "full stack",
        "fullstack", "sre", "architecte logiciel", "solution architect", "system engineer",
        "ingenieur systeme", "application", "applications", "qa engineer", "tester",
        "scrum", "product owner", "technicien support", "helpdesk", "service desk", "ict",
    ]),
    ("Santé & Soins", [
        "infirmier", "infirmiere", "nurse", "medecin", "physician", "doctor", "pharmacien",
        "pharmacist", "aide-soignant", "aide-soignante", "assc", "sage-femme", "physiotherapeute",
        "ergotherapeute", "radiologie", "soins", "medical doctor", "clinical", "clinique",
    ]),
    ("Recherche & Science", [
        "research", "recherche", "scientist", "scientifique", "chemist", "chimiste",
        "laboratory", "laboratoire", "laborantin", "laborantine", "biologist", "biologiste",
        "r&d", "postdoc", "phd", "doctorant", "doctorante", "physicist", "physicien",
        "perfumer", "parfumeur", "flavorist", "aromaticien",
    ]),
    ("Juridique & Compliance", [
        "legal", "juriste", "lawyer", "avocat", "avocate", "counsel", "compliance",
        "conformite", "kyc", "aml", "regulatory", "reglementaire", "paralegal", "notaire",
    ]),
    ("Banque & Gestion de fortune", [
        "relationship manager", "private banker", "banquier", "gestionnaire de fortune",
        "wealth", "portfolio manager", "gerant", "gerante", "investment", "trader",
        "trading", "asset management", "private banking", "custody", "credit officer",
    ]),
    ("Finance & Comptabilité", [
        "finance", "financial", "financier", "financiere", "accountant", "comptable",
        "accounting", "comptabilite", "controller", "controleur de gestion", "controlling",
        "audit", "auditor", "auditeur", "tax", "fiscal", "fiscaliste", "treasury",
        "tresorerie", "payroll", "paie", "fp&a", "billing", "facturation", "credit",
    ]),
    ("Ressources humaines", [
        "hr", "rh", "human resources", "ressources humaines", "talent", "recruiter",
        "recruteur", "recruteuse", "recruitment", "recrutement", "people partner",
        "learning", "formation", "compensation", "c&b",
    ]),
    ("Marketing & Communication", [
        "marketing", "communication", "communications", "brand", "marque", "digital marketing",
        "content", "contenu", "social media", "seo", "crm", "public relations", "media",
        "graphiste", "graphic designer", "designer", "ux", "ui", "events", "evenementiel",
    ]),
    ("Vente & Relation client", [
        "sales", "vente", "vendeur", "vendeuse", "account manager", "account executive",
        "business development", "key account", "commercial", "commerciale",
        "customer service", "service client", "customer success", "client advisor",
        "conseiller de vente", "conseillere de vente", "boutique", "store manager",
        "retail", "call center", "telesales", "commerce de detail", "detailhandel",
        "verkauf", "verkaufsberater",
    ]),
    ("Supply chain & Achats", [
        "supply chain", "logistics", "logistique", "logisticien", "logisticienne",
        "procurement", "purchasing", "achats", "acheteur", "acheteuse", "buyer",
        "warehouse", "entrepot", "planner", "planificateur", "planificatrice", "demand",
        "inventory", "inventaire", "inventaires", "stock", "shipping", "freight",
        "chartering", "operations analyst",
    ]),
    ("Ingénierie & Production", [
        "engineer", "ingenieur", "ingenieure", "mechanical", "mecanique", "mecanicien",
        "electronique", "electronics", "electrical", "electricien", "automation",
        "automaticien", "production", "manufacturing", "fabrication", "process",
        "maintenance", "quality", "qualite", "polymecanicien", "micromecanicien",
        "horloger", "horlogere", "watchmaker", "operateur", "operatrice", "technicien",
        "technicienne", "industrialisation", "methodes", "constructeur", "dessinateur",
    ]),
    ("Administration & Assistanat", [
        "assistant", "assistante", "secretaire", "secretary", "receptionist",
        "receptionniste", "office manager", "administrative", "administratif",
        "administrative assistant", "employe de commerce", "employee de commerce",
        "back office", "gestionnaire administratif",
    ]),
    ("Direction & Conseil", [
        "director", "directeur", "directrice", "head of", "chief", "ceo", "cfo", "cto",
        "coo", "vice president", "vp", "general manager", "strategy", "strategie",
        "consultant", "consultante", "project manager", "chef de projet", "program manager",
        "transformation", "pmo",
    ]),
    ("Hôtellerie & Services", [
        "cuisinier", "cuisiniere", "chef de cuisine", "serveur", "serveuse", "barista",
        "hotel", "hotellerie", "concierge", "nettoyage", "cleaning", "agent de securite",
        "security guard", "chauffeur", "driver", "housekeeping", "conducteur de vehicules",
        # métiers de bouche (Coop) : boucherie, boulangerie, restauration
        "restauration", "boucher", "bouchere", "boucherie", "poissonnier", "boulanger",
        "boulangere", "patissier", "confiseur",
    ]),
]

SENIORITY_RULES: list[tuple[str, list[str]]] = [
    ("Stage / Apprentissage", [
        "intern", "internship", "stage", "stagiaire", "apprenti", "apprentie",
        "apprentissage", "apprentice", "trainee", "werkstudent", "graduate program",
        "summer analyst",
    ]),
    ("Direction", [
        "director", "directeur", "directrice", "head of", "chief", "vice president", "vp",
        "ceo", "cfo", "cto", "coo", "general manager",
    ]),
    ("Senior / Lead", [
        "senior", "sr", "lead", "principal", "expert", "experte", "manager",
        "responsable", "chef", "cadre", "kader", "fuhrungskrafte",
    ]),
    ("Junior", [
        "junior", "jr", "entry level", "debutant", "debutante", "graduate", "postdoc",
        "post-doc", "postdoctoral", "phd", "doctorant", "doctorante", "doctoral",
    ]),
]
UNKNOWN_SENIORITY = "Non précisé"
MID_LEVEL = "Confirmé·e"

# « 5+ years of experience », « 3-5 years' experience », « 3 ans d'expérience », « five years
# of relevant experience », « 5 Jahre Berufserfahrung ». Sur la description normalisée (sans
# accents). Une fourchette compte pour son milieu : « 2 to 5 years », c'est un profil
# confirmé, pas junior (« 2-5 » → 3,5).
_NUMBERS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten".split())}
_NUMBERS |= {w: i for i, w in enumerate(
    "zero un deux trois quatre cinq six sept huit neuf dix".split()) if i}
_YEARS = re.compile(
    rf"\b(\d{{1,2}}|{'|'.join(_NUMBERS)})\s*\+?\s*(?:(?:-|–|a|to)\s*(\d{{1,2}})\s*)?"
    r"(?:years?|yrs|ans|annees|jahre?n?)\b[^.;]{0,40}?(?:experience|erfahrung)")


_FAMILIES = compile_keywords(FAMILY_RULES)
_SENIORITY = compile_keywords(SENIORITY_RULES)
# « 80-100% », « 80 – 100 % », « 50% », « Taux d'activité : 100 % »
_WORKLOAD = re.compile(r"(\d{2,3})\s*%?\s*[-–à]\s*(\d{2,3})\s*%|(\d{2,3})\s*%")


@dataclass(frozen=True)
class Classification:
    family: str
    family_keyword: str | None  # le mot-clé qui a décidé : l'explication de la règle
    seniority: str
    workload_min: int | None
    workload_max: int | None


def workload(title: str) -> tuple[int | None, int | None]:
    """Extrait le taux d'activité d'un titre suisse : « Comptable 80-100% » → (80, 100)."""
    match = _WORKLOAD.search(title)
    if not match:
        return None, None
    low, high, single = match.groups()
    values = [int(v) for v in (low, high, single) if v]
    values = [v for v in values if 10 <= v <= 100]
    if not values:
        return None, None
    return min(values), max(values)


def years_of_experience(description: str | None) -> float | None:
    """Le nombre d'années d'expérience demandé (la première mention), None s'il n'y en a pas."""
    match = _YEARS.search(normalize(description or ""))
    if not match:
        return None
    low, high = match.group(1), match.group(2)
    low = int(low) if low.isdigit() else _NUMBERS[low]
    years = (low + int(high)) / 2 if high and int(high) > low else low
    return years if years <= 30 else None  # « 150 years of experience » : l'histoire de la maison


def seniority_of(title: str, description: str | None = None, level: str | None = None) -> str:
    """Le titre d'abord (il est explicite), puis le niveau déclaré par l'ATS, puis les années
    d'expérience demandées dans la description."""
    for text in (title, level):
        found, _ = first_match(_SENIORITY, normalize(text or ""), default=None)
        if found:
            return found
    years = years_of_experience(description)
    if years is None:
        return UNKNOWN_SENIORITY
    return "Junior" if years <= 2 else MID_LEVEL if years <= 5 else "Senior / Lead"


def classify(title: str, description: str | None = None, category: str | None = None,
             level: str | None = None) -> Classification:
    """Le titre d'abord ; à défaut, la catégorie de l'ATS (Coop : « Vente Food »)."""
    family, keyword = first_match(_FAMILIES, normalize(title), default=OTHER)
    if family == OTHER and category:
        family, keyword = first_match(_FAMILIES, normalize(category), default=OTHER)
    seniority = seniority_of(title, description, level)
    low, high = workload(title)
    return Classification(family=family, family_keyword=keyword, seniority=seniority,
                          workload_min=low, workload_max=high)
