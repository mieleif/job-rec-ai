"""HTML d'annonce → Markdown : chaque règle sur un cas écrit à la main, puis la forme réelle du
HTML de chaque connecteur (fixtures enregistrées sur les vrais ATS)."""

import json
import re
from collections import Counter
from pathlib import Path

import pytest

from job_rec_ai.connectors import REGISTRY
from job_rec_ai.markdown import html_to_markdown, join_markdown, text_to_markdown
from job_rec_ai.text import tokenize

FIXTURES = Path(__file__).parent / "fixtures"


def test_titres_jamais_de_niveau_1():
    md = html_to_markdown("<h1>A</h1><h2>B</h2><h3>C</h3><h4>D</h4><h6>E</h6>")
    assert md == "## A\n\n## B\n\n### C\n\n### D\n\n### E"


def test_paragraphes_gras_italique():
    md = html_to_markdown("<p>Intro <b>gras</b> et <em>penché</em>.</p><p>Suite <strong> "
                          "espacé </strong>ici</p>")
    assert md == "Intro **gras** et *penché*.\n\nSuite **espacé** ici"


def test_listes_aplaties_sur_un_niveau():
    md = html_to_markdown("<ul><li>Python</li><li>SQL<ul><li>dbt</li></ul></li></ul>"
                          "<ol start='3'><li>un</li><li><p>deux</p><p>suite</p></li></ol>")
    assert md == "- Python\n- SQL\n- dbt\n\n3. un\n4. deux suite"


def test_liens_http_seulement():
    md = html_to_markdown("<p>Voir <a href='https://ex.ch/a b(1)'>le site</a>, "
                          "<a href='mailto:rh@ex.ch'>rh@ex.ch</a> et "
                          "<a href='javascript:alert(1)'>ici</a>.</p>")
    assert md == "Voir [le site](https://ex.ch/a%20b%281%29), rh@ex.ch et ici."


def test_ni_image_ni_script_ni_style_ni_iframe_ni_html_brut():
    md = html_to_markdown("<style>p{color:red}</style><p>Texte<img src='x.png' alt='logo'>"
                          "<script>alert(1)</script><iframe src='x'>cadre</iframe>"
                          "<button>Postuler</button> &lt;b&gt;fin&lt;/b&gt;</p>")
    assert md == r"Texte \<b\>fin\</b\>"


def test_caracteres_markdown_du_texte_echappes():
    md = html_to_markdown("<p># pas un titre, *étoile*, _x_, [lien], a|b, ~x~</p>"
                          "<p>2026. Une année</p><p>+ plus</p><p>&gt; citation</p>")
    assert md == ("\\# pas un titre, \\*étoile\\*, \\_x\\_, \\[lien\\], a\\|b, \\~x\\~\n\n"
                  "2026\\. Une année\n\n\\+ plus\n\n\\> citation")


def test_tableau_aplati_en_liste():
    md = html_to_markdown("<table><tr><th>Taux</th><td>80 %</td></tr>"
                          "<tr><td>Lieu</td><td>Genève</td></tr></table><p>Après</p>")
    assert md == "- Taux · 80 %\n- Lieu · Genève\n\nAprès"


def test_tableau_de_mise_en_page_lu_comme_du_texte():
    md = html_to_markdown("<table><tr><td><p>Intro</p><ul><li>a</li></ul></td></tr></table>")
    assert md == "Intro\n\n- a"


def test_paragraphe_court_en_gras_devient_un_titre():
    md = html_to_markdown("<p><strong>Vos missions</strong></p><p><b>1.</b> <b>Contexte</b></p>"
                          "<p><strong>Une phrase en gras.</strong></p>"
                          "<p><strong>Lieu :</strong> Genève<br><strong>Taux</strong><br>80 %</p>")
    assert md == ("### Vos missions\n\n### 1. Contexte\n\n**Une phrase en gras.**\n\n"
                  "**Lieu :** Genève\n\n**Taux**\n\n80 %")


def test_puces_typographiques_devenues_liste():
    md = html_to_markdown("<p>• Analyser<br>• Rédiger<br>Texte</p>"
                          "<p>Missions : • Lire • Écrire</p><p>Genève • Lausanne</p>")
    assert md == ("- Analyser\n- Rédiger\n\nTexte\n\nMissions :\n\n- Lire\n- Écrire\n\n"
                  "Genève • Lausanne")


def test_gras_coupe_par_un_bloc_ou_un_saut_de_ligne():
    assert html_to_markdown("<p><b>Début<br>fin</b> du texte</p>") == (
        "**Début**\n\n**fin** du texte")
    assert html_to_markdown("<b>A<p>long texte qui suit.</p></b>") == (
        "### A\n\n**long texte qui suit.**")


def test_html_echappe_et_entites_doublement_echappees():
    assert html_to_markdown("&lt;p&gt;Python &amp;amp; SQL&lt;/p&gt;") == "Python & SQL"
    assert html_to_markdown("<p>l&amp;#039;État</p>") == "l'État"


def test_vide():
    assert html_to_markdown(None) == html_to_markdown("") == text_to_markdown(None) == ""
    assert html_to_markdown("<p> </p><p>&nbsp;</p>") == ""


def test_texte_brut_en_paragraphes():
    md = text_to_markdown("Première ligne.\n\nDeuxième *ligne* ici.Troisième\n- puce\nl&#039;fin")
    assert md == ("Première ligne.\n\nDeuxième \\*ligne\\* ici.\n\nTroisième\n\n- puce\n\n"
                  "l'fin")


def test_plusieurs_champs_reunis():
    assert join_markdown(["## A", "", "texte"]) == "## A\n\ntexte"


# --- la forme réelle du HTML de chaque connecteur -----------------------------------------

def _jobs(ats: str):
    payload = json.loads((FIXTURES / f"{ats}.json").read_text(encoding="utf-8"))
    return REGISTRY[payload["ats"]].parse(payload)


def _words(markdown: str) -> Counter:
    """Les mots lisibles du Markdown : sans cibles de liens, échappements ni marques de titre."""
    text = re.sub(r"\]\([^)]*\)", "]", markdown)
    text = re.sub(r"\\(.)", r"\1", text)
    return Counter(w for w in tokenize(text) if w.strip("#"))


ALL_ATS = sorted(p.stem for p in FIXTURES.glob("*.json"))


@pytest.mark.parametrize("ats", ALL_ATS)
def test_chaque_connecteur_rend_un_markdown_propre_et_complet(ats):
    for job in _jobs(ats):
        md = job.description_markdown
        assert md, f"{ats} : {job.title} sans Markdown"
        assert not re.search(r"(?<!\\)<[a-zA-Z/!]", md), "HTML brut"
        assert not re.search(r"^# ", md, re.M), "titre de niveau 1"
        assert "&nbsp;" not in md and "&amp;" not in md
        # Même texte que la description brute (BM25), à la structure près : les boutons du
        # site (CERN : « View more ») ne sont pas du contenu
        words, plain = _words(md), Counter(tokenize(job.description))
        assert sum((plain - words).values()) <= max(2, 0.02 * sum(plain.values())), job.title
        assert sum((words - plain).values()) <= 2, job.title


@pytest.mark.parametrize("ats, expected", [
    ("cern", ["## ", "### Your responsibilities", "- Support experienced",
              "[CERN Member State or Associate Member State](https://home.cern/"]),
    ("greenhouse", ["### Role Overview", "- ", "[Twitter](https://x.com/ProtonPrivacy)"]),
    ("oracle", ["### Main responsibilities", "- "]),
    ("phenom", ["### Votre Principale mission :", "- "]),
    ("prospective", ["- "]),
    ("smartrecruiters", ["## Description du poste", "## Qualifications"]),
    ("successfactors", ["### Vos missions principales:", "- "]),
    ("taleo", ["### 1. Organizational Context", "### 2. Duties and Responsibilities"]),
    ("uncareers", ["### Responsibilities", "- Review all incoming correspondence"]),
    ("workable", ["### Requirements", "- "]),
    ("workday", ["### The Role:", "- Manage sourcing for electronic mechanical components."]),
])
def test_structure_gardee(ats, expected):
    markdown = "\n\n".join(j.description_markdown for j in _jobs(ats))
    for fragment in expected:  # titres et puces en début de ligne ; liens n'importe où
        anchor = "^" if fragment.startswith(("#", "- ")) else ""
        assert re.search(anchor + re.escape(fragment), markdown, re.M), fragment


@pytest.mark.parametrize("ats", ["cornerstone", "jsonld"])
def test_annonces_sans_html_en_paragraphes(ats):
    """Cornerstone et le JSON-LD de l'État de Genève publient du texte brut."""
    for job in _jobs(ats):
        assert not re.search(r"^(#|- )", job.description_markdown, re.M)
    first = _jobs("jsonld")[0].description_markdown
    assert "territoire cantonal.\n\nDans ce cadre" in first  # le saut de paragraphe perdu
