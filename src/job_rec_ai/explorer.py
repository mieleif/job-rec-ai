"""L'explorateur d'offres : une page HTML autonome, générée depuis la base après une collecte.

Pourquoi une page statique plutôt qu'une app (Streamlit viendra en M7, avec les swipes) ?
Aucun serveur à lancer, elle s'ouvre en deux secondes, et le filtrage de ~2 000 offres se
fait sans peine dans le navigateur. Les données sont embarquées en JSON dans la page ; tout
le reste (filtres, regroupement, tri) est du JavaScript sans dépendance.
"""

import html
import json
from datetime import date

TEMPLATE = r"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Offres en Suisse romande</title>
<style>
:root {
  color-scheme: light;
  --bg: #f9f9f7; --surface: #ffffff; --ink: #0b0b0b; --ink-2: #52514e; --muted: #898781;
  --line: #e6e5e1; --accent: #2a78d6; --accent-ink: #ffffff; --chip: #f0efec;
  --new: #0a7d3c; --agency: #9a5b00; --focus: #2a78d6;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --bg: #0d0d0d; --surface: #1a1a19; --ink: #f0efec; --ink-2: #c3c2b7; --muted: #898781;
    --line: #2c2c2a; --accent: #3987e5; --accent-ink: #ffffff; --chip: #262624;
    --new: #3fbf6f; --agency: #e0a43a; --focus: #3987e5;
  }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--ink);
  font: 15px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; }
a { color: inherit; }
header { padding: 28px 16px 8px; max-width: 1280px; margin: 0 auto; }
h1 { font-size: 24px; margin: 0 0 4px; letter-spacing: -0.01em; }
.sub { color: var(--ink-2); margin: 0; }
.bar { background: var(--bg); border-bottom: 1px solid var(--line); }
/* épinglée seulement sur grand écran : sur un téléphone, elle mangerait la moitié de l'écran */
@media (min-width: 900px) { .bar { position: sticky; top: 0; z-index: 2; } }
.bar-inner { max-width: 1280px; margin: 0 auto; padding: 12px 16px; display: flex;
  flex-wrap: wrap; gap: 8px; align-items: center; }
.bar input[type=search] { flex: 1 1 240px; min-width: 0; }
.bar input[type=search], .bar select { font: inherit; color: var(--ink);
  background: var(--surface); border: 1px solid var(--line); border-radius: 8px;
  padding: 7px 10px; }
.bar select { flex: 0 1 auto; max-width: 100%; }
.bar label.toggle { display: inline-flex; gap: 6px; align-items: center; color: var(--ink-2);
  white-space: nowrap; }
button { font: inherit; cursor: pointer; border-radius: 8px; border: 1px solid var(--line);
  background: var(--surface); color: var(--ink); padding: 7px 12px; }
button:hover { border-color: var(--muted); }
:focus-visible { outline: 2px solid var(--focus); outline-offset: 2px; }
.count { color: var(--ink-2); margin-left: auto; white-space: nowrap; }
main { max-width: 1280px; margin: 0 auto; padding: 8px 16px 48px; }
details.group { margin-top: 18px; }
details.group > summary { list-style: none; cursor: pointer; display: flex; align-items: baseline;
  gap: 10px; padding: 6px 0; border-bottom: 1px solid var(--line); }
details.group > summary::-webkit-details-marker { display: none; }
details.group > summary::before { content: "▸"; color: var(--muted); width: 12px; }
details.group[open] > summary::before { content: "▾"; }
.group-name { font-weight: 650; font-size: 17px; }
.group-n { color: var(--muted); font-variant-numeric: tabular-nums; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 320px), 1fr));
  gap: 12px; margin-top: 12px; }
.card { background: var(--surface); border: 1px solid var(--line); border-radius: 12px;
  padding: 14px 16px; display: flex; flex-direction: column; gap: 8px; min-width: 0; }
.card:hover { border-color: var(--muted); }
.card h3 { margin: 0; font-size: 15.5px; line-height: 1.3; }
.card h3 a { text-decoration: none; }
.card h3 a:hover { text-decoration: underline; }
.meta { color: var(--ink-2); font-size: 13.5px; overflow-wrap: anywhere; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chip { background: var(--chip); color: var(--ink-2); border-radius: 999px; padding: 2px 9px;
  font-size: 12.5px; white-space: nowrap; }
.chip.new { color: var(--new); font-weight: 600; }
.chip.agency { color: var(--agency); font-weight: 600; }
.excerpt { color: var(--ink-2); font-size: 13.5px; margin: 0; display: -webkit-box;
  -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
.foot { color: var(--muted); font-size: 12.5px; margin-top: auto; }
.more { margin-top: 12px; }
.empty { color: var(--ink-2); padding: 40px 0; text-align: center; }
@media (max-width: 600px) {
  h1 { font-size: 20px; }
  /* filtres sur deux colonnes : la liste commence plus haut */
  .bar-inner { display: grid; grid-template-columns: 1fr 1fr; }
  .bar-inner > input[type=search], .bar-inner > .count { grid-column: 1 / -1; }
  .bar select { width: 100%; }
  .count { margin-left: 0; }
}
</style>
</head>
<body>
<header>
  <h1>Offres d'emploi en Suisse romande</h1>
  <p class="sub">__SUMMARY__</p>
</header>
<div class="bar"><div class="bar-inner" role="search">
  <input type="search" id="q" placeholder="Rechercher un titre, un employeur, un lieu…"
         aria-label="Rechercher">
  <select id="canton" aria-label="Canton"></select>
  <select id="family" aria-label="Famille de métiers"></select>
  <select id="seniority" aria-label="Séniorité"></select>
  <select id="language" aria-label="Langue"></select>
  <select id="publisher" aria-label="Publiée par"></select>
  <label class="toggle"><input type="checkbox" id="fresh"> moins de 7 jours</label>
  <select id="group" aria-label="Regrouper par">
    <option value="family">Regrouper : famille</option>
    <option value="company">Regrouper : employeur</option>
    <option value="canton">Regrouper : canton</option>
    <option value="none">Sans regroupement</option>
  </select>
  <select id="sort" aria-label="Trier par">
    <option value="recent">Tri : plus récentes</option>
    <option value="company">Tri : employeur</option>
    <option value="title">Tri : titre</option>
  </select>
  <button id="reset" type="button">Réinitialiser</button>
  <span class="count" id="count" aria-live="polite"></span>
</div></div>
<main id="results"></main>
<script id="data" type="application/json">__DATA__</script>
<script>
const JOBS = JSON.parse(document.getElementById("data").textContent);
const TODAY = new Date("__TODAY__T00:00:00");
const PAGE = 24;
const LABELS = {
  canton: "Tous les cantons", family: "Toutes les familles",
  seniority: "Toutes les séniorités", language: "Toutes les langues",
  publisher: "Employeurs et agences",
};
const LANG = { fr: "français", en: "anglais", de: "allemand", other: "autre langue" };
const SENIORITY_ORDER = ["Stage / Apprentissage", "Junior", "Confirmé·e", "Senior / Lead",
                         "Direction", "Non précisé"];
const $ = (id) => document.getElementById(id);
const days = (iso) => iso ? Math.round((TODAY - new Date(iso + "T00:00:00")) / 864e5) : null;
const norm = (s) => (s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
for (const j of JOBS) {
  j._text = norm([j.title, j.company, j.location, j.family].join(" "));
  j._age = days(j.posted_at || j.first_seen);
  j._new = days(j.first_seen) !== null && days(j.first_seen) <= 3;
  j.publisher_type = j.publisher_type || "employeur";
}

function fillSelect(id, key, order, label) {
  const counts = {};
  for (const j of JOBS) { const v = j[key] || "(inconnu)"; counts[v] = (counts[v] || 0) + 1; }
  const values = Object.keys(counts).sort((a, b) =>
    order ? order.indexOf(a) - order.indexOf(b) : counts[b] - counts[a]);
  $(id).innerHTML = `<option value="">${LABELS[id]}</option>` + values.map(v =>
    `<option value="${esc(v)}">${esc(label ? label(v) : v)} (${counts[v]})</option>`).join("");
}
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;",
    '"': "&quot;", "'": "&#39;"}[c]));
}
fillSelect("canton", "canton");
fillSelect("family", "family");
fillSelect("seniority", "seniority", SENIORITY_ORDER);
fillSelect("language", "language", null, v => LANG[v] || v);
fillSelect("publisher", "publisher_type", null, v => v === "agence" ? "agences" : "employeurs");

const FILTERS = { canton: "canton", family: "family", seniority: "seniority",
                  language: "language", publisher: "publisher_type" };
const expanded = new Set();

function workload(j) {
  if (!j.workload_min) return null;
  return j.workload_min === j.workload_max ? `${j.workload_min} %`
    : `${j.workload_min}–${j.workload_max} %`;
}
function age(j) {
  if (j._age === null) return "";
  if (j._age <= 0) return "aujourd'hui";
  if (j._age === 1) return "hier";
  return j._age < 60 ? `il y a ${j._age} jours` : `il y a ${Math.round(j._age / 30)} mois`;
}
const chip = (text) => `<span class="chip">${esc(text)}</span>`;
function card(j) {
  const chips = [
    j._new ? `<span class="chip new">nouvelle</span>` : "",
    j.publisher_type === "agence" ? `<span class="chip agency">agence</span>` : "",
    j.canton ? `<span class="chip">${esc(j.canton)}</span>` : "",
    j.seniority && j.seniority !== "Non précisé" ? chip(j.seniority) : "",
    workload(j) ? chip(workload(j)) : "",
    // « other » veut surtout dire « texte trop court pour trancher » : pas de pastille
    j.language && !["fr", "other"].includes(j.language) ? chip(LANG[j.language] || j.language) : "",
  ].join("");
  // Coop répète le titre en guise de description : rien à montrer
  const excerpt = j.excerpt && norm(j.excerpt).trim() !== norm(j.title).trim()
    ? `<p class="excerpt">${esc(j.excerpt)}</p>` : "";
  const when = age(j) ? `${j.posted_at ? "publiée" : "vue"} ${age(j)}` : "";
  return `<article class="card">
    <h3><a href="${esc(j.url)}" target="_blank" rel="noopener">${esc(j.title)}</a></h3>
    <div class="meta">${esc(j.company)} · ${esc(j.location || "lieu non précisé")}</div>
    <div class="chips">${chips}</div>${excerpt}
    <div class="foot">${esc(j.family)}${when ? " · " + when : ""}</div>
  </article>`;
}
function sorter(kind) {
  if (kind === "company") {
    return (a, b) => a.company.localeCompare(b.company, "fr") ||
      a.title.localeCompare(b.title, "fr");
  }
  if (kind === "title") return (a, b) => a.title.localeCompare(b.title, "fr");
  return (a, b) => (a._age ?? 1e9) - (b._age ?? 1e9);
}
function render() {
  const q = norm($("q").value).split(/\s+/).filter(Boolean);
  const active = Object.entries(FILTERS).map(([id, key]) => [key, $(id).value])
    .filter(([, v]) => v);
  const fresh = $("fresh").checked;
  const rows = JOBS.filter(j =>
    q.every(w => j._text.includes(w)) &&
    active.every(([key, v]) => (j[key] || "(inconnu)") === v) &&
    (!fresh || (j._age !== null && j._age <= 7))
  ).sort(sorter($("sort").value));
  const by = $("group").value;
  const groups = new Map();
  for (const j of rows) {
    const g = by === "none" ? "Toutes les offres" : (j[by] || "(inconnu)");
    if (!groups.has(g)) groups.set(g, []);
    groups.get(g).push(j);
  }
  // les plus gros groupes d'abord, mais « Autre » et « (inconnu) » toujours à la fin
  const last = (name) => name === "Autre" || name === "(inconnu)" ? 1 : 0;
  const ordered = [...groups.entries()].sort((a, b) => last(a[0]) - last(b[0]) ||
    b[1].length - a[1].length || a[0].localeCompare(b[0], "fr"));
  const employers = new Set(rows.map(j => j.company)).size;
  const plural = (n, word) => `${n} ${word}${n > 1 ? "s" : ""}`;
  $("count").textContent = `${plural(rows.length, "offre")} · ${plural(employers, "employeur")}`;
  if (!rows.length) {
    $("results").innerHTML = `<p class="empty">Aucune offre ne correspond à ces filtres.</p>`;
    return;
  }
  $("results").innerHTML = ordered.map(([name, list], i) => {
    const shown = expanded.has(name) ? list : list.slice(0, PAGE);
    const more = list.length - shown.length;
    return `<details class="group" ${i < 6 || ordered.length <= 8 ? "open" : ""}>
      <summary><span class="group-name">${esc(name)}</span>
      <span class="group-n">${list.length}</span></summary>
      <div class="grid">${shown.map(card).join("")}</div>
      ${more > 0 ? `<button class="more" type="button" data-group="${esc(name)}">
        Voir les ${more} autres</button>` : ""}
    </details>`;
  }).join("");
}
$("results").addEventListener("click", e => {
  const b = e.target.closest("button.more");
  if (b) { expanded.add(b.dataset.group); render(); }
});
let timer;
$("q").addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(render, 120); });
for (const id of [...Object.keys(FILTERS), "fresh", "group", "sort"]) {
  $(id).addEventListener("change", () => { expanded.clear(); render(); });
}
$("reset").addEventListener("click", () => {
  $("q").value = ""; $("fresh").checked = false;
  for (const id of Object.keys(FILTERS)) $(id).value = "";
  $("group").value = "family"; $("sort").value = "recent";
  expanded.clear(); render();
});
render();
</script>
</body>
</html>
"""


def render(jobs: list[dict], today: date | None = None) -> str:
    """Les offres → la page. Le JSON est embarqué tel quel : « </ » est neutralisé pour
    qu'un titre contenant « </script> » ne puisse pas refermer la balise."""
    today = today or date.today()
    employers = len({j["company"] for j in jobs})
    cantons = len({j["canton"] for j in jobs if j["canton"]})
    summary = (f"{len(jobs)} offres actives · {employers} employeurs · {cantons} cantons · "
               f"mise à jour le {today:%d.%m.%Y}")
    data = json.dumps(jobs, ensure_ascii=False).replace("</", "<\\/")
    return (TEMPLATE.replace("__SUMMARY__", html.escape(summary))
            .replace("__TODAY__", today.isoformat())
            .replace("__DATA__", data))
