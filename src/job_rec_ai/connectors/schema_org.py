"""Microdonnées schema.org JobPosting : le balisage des annonces que lit Google for Jobs.

Les sites carrière l'ajoutent pour être référencés (itemprop="title", "datePosted",
"jobLocation"…). C'est un contrat plus stable que leurs classes CSS, qui changent à chaque
refonte : SmartRecruiters et SuccessFactors s'en servent tous les deux.
"""

from bs4 import BeautifulSoup, Tag


class JobPostingPage:
    def __init__(self, html: str):
        self.soup = BeautifulSoup(html, "html.parser")

    def tag(self, name: str) -> Tag | None:
        return self.soup.find(attrs={"itemprop": name})

    def tags(self, name: str) -> list[Tag]:
        """Toutes les balises d'une propriété : certains sites découpent la description en
        plusieurs blocs (accroche, missions, profil…)."""
        return self.soup.find_all(attrs={"itemprop": name})

    def prop(self, name: str) -> str | None:
        """Valeur d'une propriété : attribut content (balise <meta>) ou texte de la balise."""
        tag = self.tag(name)
        if tag is None:
            return None
        return tag.get("content") or tag.get_text(" ", strip=True) or None

    def markup(self) -> str:
        """Seulement les balises de microdonnées (sans le gabarit de page autour) : tout ce
        que lisent prop() et tags(), dix fois plus léger à archiver que la page entière."""
        roots = [tag for tag in self.soup.find_all(attrs={"itemprop": True})
                 if tag.find_parent(attrs={"itemprop": True}) is None]
        return "\n".join(map(str, roots))
