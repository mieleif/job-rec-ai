"""Le modèle de données central : une offre d'emploi normalisée, quel que soit l'ATS d'origine."""

from datetime import date

from pydantic import BaseModel, ConfigDict, HttpUrl, field_validator


class Job(BaseModel):
    """Une offre d'emploi.

    Les six premiers champs forment le contrat de la ROADMAP (checkpoint M1). Les suivants
    sont optionnels : ils gardent la trace de la provenance (source, source_id) et des
    facettes utiles au tri, sans casser les offres créées avec le contrat minimal.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    title: str
    company: str
    url: HttpUrl
    location: str
    description: str
    language: str | None = None
    posted_at: date | None = None

    # Provenance : quel connecteur, et l'identifiant de l'offre dans cet ATS
    source: str | None = None
    source_id: str | None = None
    # Texte brut de l'ATS (« Full time », « Temps partiel »…), interprété plus tard
    employment_type: str | None = None
    # Le classement de l'ATS lui-même, quand il en publie un (Coop : « Vente Food »,
    # « Collaborateur ») : en texte brut, interprété par families.py
    category: str | None = None
    level: str | None = None
    # L'annonce avec sa structure (titres, listes, gras), pour la lire : voir markdown.py.
    # `description` reste le texte brut sur une ligne, celui que lit le moteur (BM25).
    description_markdown: str | None = None

    @field_validator("title", "company")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        # str_strip_whitespace a déjà retiré les espaces : « ␣␣␣ » devient « »
        if not value:
            raise ValueError("ne doit pas être vide")
        return value
