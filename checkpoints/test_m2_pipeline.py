"""Checkpoint M2 : pipeline.

Contrat attendu :
- job_rec_ai.text.clean_html(html) -> str : texte sans balises, sans le contenu des
  <script>/<style>, entités décodées, espaces multiples réduits.
- job_rec_ai.text.detect_language(text) -> "fr" | "en" | "other".
- job_rec_ai.pipeline.diff_snapshots(old, new) -> objet avec .new, .updated, .expired
  (listes de Job). Clé = URL. « updated » = même URL mais titre ou description changés.
"""

SAMPLE_HTML = """
<div><h2>Data Engineer</h2><script>trackUser();</script><style>.x{color:red}</style>
<p>Vous   rejoindrez  l'équipe R&amp;D.</p><ul><li>Python</li><li>SQL</li></ul></div>
"""


def test_clean_html_retire_les_balises(need):
    """Retirer toutes les balises HTML."""
    clean_html = need("job_rec_ai.text", "clean_html")
    out = clean_html(SAMPLE_HTML)
    assert "<" not in out and ">" not in out
    assert "Data Engineer" in out and "Python" in out


def test_clean_html_ignore_script_et_style(need):
    """Ignorer complètement le contenu des <script> et <style>."""
    clean_html = need("job_rec_ai.text", "clean_html")
    out = clean_html(SAMPLE_HTML)
    assert "trackUser" not in out and "color:red" not in out


def test_clean_html_decode_les_entites(need):
    """Décoder les entités HTML (&amp; → &) et réduire les espaces multiples."""
    clean_html = need("job_rec_ai.text", "clean_html")
    out = clean_html(SAMPLE_HTML)
    assert "R&D" in out
    assert "  " not in out


def test_detect_language_fr_en(need):
    """Reconnaître une offre en français et une offre en anglais."""
    detect_language = need("job_rec_ai.text", "detect_language")
    fr = "Nous recherchons un ingénieur de données passionné pour rejoindre notre équipe à Genève."
    en = "We are looking for a passionate data engineer to join our team in Geneva."
    assert detect_language(fr) == "fr"
    assert detect_language(en) == "en"


def test_detect_language_vide(need):
    """Renvoyer « other » pour un texte vide."""
    detect_language = need("job_rec_ai.text", "detect_language")
    assert detect_language("") == "other"


def _jobs(need):
    Job = need("job_rec_ai.models", "Job")

    def make(n, title="Data Engineer", desc="Pipelines."):
        return Job(title=title, company="Acme", url=f"https://acme.example/jobs/{n}",
                   location="Genève", description=desc)

    return make


def test_diff_detecte_nouvelles_et_expirees(need):
    """Détecter les offres nouvelles et les offres expirées entre deux collectes."""
    diff_snapshots = need("job_rec_ai.pipeline", "diff_snapshots")
    make = _jobs(need)
    old, new = [make(1), make(2)], [make(2), make(3)]
    d = diff_snapshots(old, new)
    assert {str(j.url) for j in d.new} == {"https://acme.example/jobs/3"}
    assert {str(j.url) for j in d.expired} == {"https://acme.example/jobs/1"}
    assert list(d.updated) == []


def test_diff_detecte_les_modifications(need):
    """Détecter une offre dont la description a changé (même URL)."""
    diff_snapshots = need("job_rec_ai.pipeline", "diff_snapshots")
    make = _jobs(need)
    d = diff_snapshots([make(1, desc="v1")], [make(1, desc="v2")])
    assert [j.description for j in d.updated] == ["v2"]
    assert list(d.new) == [] and list(d.expired) == []
