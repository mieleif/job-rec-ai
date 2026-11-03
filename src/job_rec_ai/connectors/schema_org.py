"""Microdonnées schema.org JobPosting : le balisage des annonces que lit Google for Jobs.

Les sites carrière l'ajoutent pour être référencés (itemprop="title", "datePosted",
"jobLocation"…). C'est un contrat plus stable que leurs classes CSS, qui changent à chaque
refonte : SmartRecruiters et SuccessFactors s'en servent tous les deux.
"""

import json
import re

from bs4 import BeautifulSoup, Tag

_JSON_LD = re.compile(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', re.S | re.I)


def json_ld_job_posting(html: str) -> dict | None:
    """Le JobPosting écrit en JSON-LD (<script type="application/ld+json">), la même
    information que les microdonnées, mais sous forme d'objet JSON. Il peut être seul,
    dans une liste, ou dans un « @graph » avec d'autres objets (site, fil d'Ariane…)."""
    for block in _JSON_LD.findall(html):
        try:
            data = json.loads(block, strict=False)  # strict=False : retours à la ligne bruts
        except json.JSONDecodeError:
            continue
        nodes = data if isinstance(data, list) else data.get("@graph", [data])
        for node in nodes:
            if isinstance(node, dict) and node.get("@type") == "JobPosting":
                return node
    return None


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
