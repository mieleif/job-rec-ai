"""Classement par règles : famille de métier, séniorité et taux d'activité, à partir du titre.

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
        "retail", "call center", "telesales",
    ]),
    ("Supply chain & Achats", [
        "supply chain", "logistics", "logistique", "logisticien", "logisticienne",
        "procurement", "purchasing", "achats", "acheteur", "acheteuse", "buyer",
        "warehouse", "entrepot", "planner", "planificateur", "planificatrice", "demand",
        "inventory", "stock", "shipping", "freight", "chartering", "operations analyst",
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
        "security guard", "chauffeur", "driver", "housekeeping",
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
        "responsable", "chef",
    ]),
    ("Junior", ["junior", "jr", "entry level", "debutant", "debutante"]),
]


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


def classify(title: str) -> Classification:
    norm = normalize(title)
    family, keyword = first_match(_FAMILIES, norm, default=OTHER)
    seniority, _ = first_match(_SENIORITY, norm, default="Confirmé·e")
    low, high = workload(title)
    return Classification(family=family, family_keyword=keyword, seniority=seniority,
                          workload_min=low, workload_max=high)
