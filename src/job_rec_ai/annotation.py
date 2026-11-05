"""Page HTML autonome pour noter les offres d'un pool (0/1/2), comme l'explorateur.

Les notes vivent dans le navigateur (localStorage) ; « Copier les notes » met le JSON
{url: note} dans le presse-papiers, à coller dans le chat (ou à importer avec
`job-rec-ai eval --import`). Les offres sont mélangées et sans score : le juge ne doit pas
savoir quelle méthode les a proposées.
"""

import html
import json

EXCERPT = 900

TEMPLATE = r"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Noter les offres</title>
<style>
:root {
  color-scheme: light;
  --bg: #f9f9f7; --surface: #ffffff; --ink: #0b0b0b; --ink-2: #52514e; --muted: #898781;
  --line: #e6e5e1; --accent: #2a78d6; --chip: #f0efec; --focus: #2a78d6;
  --g0: #8a8984; --g1: #9a5b00; --g2: #0a7d3c;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --bg: #0d0d0d; --surface: #1a1a19; --ink: #f0efec; --ink-2: #c3c2b7; --muted: #898781;
    --line: #2c2c2a; --accent: #3987e5; --chip: #262624; --focus: #3987e5;
    --g0: #a3a29c; --g1: #e0a43a; --g2: #3fbf6f;
  }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--ink);
  font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
a { color: var(--accent); }
header, main { max-width: 860px; margin: 0 auto; padding: 0 16px; }
header { padding-top: 24px; }
h1 { font-size: 22px; margin: 0 0 6px; }
.sub, .scale { color: var(--ink-2); margin: 0 0 8px; }
.scale b { color: var(--ink); }
.bar { position: sticky; top: 0; z-index: 2; background: var(--bg);
  border-bottom: 1px solid var(--line); }
.bar-inner { max-width: 860px; margin: 0 auto; padding: 10px 16px; display: flex;
  flex-wrap: wrap; gap: 8px; align-items: center; }
.progress { flex: 1 1 200px; color: var(--ink-2); }
.meter { height: 6px; background: var(--chip); border-radius: 3px; margin-top: 4px; }
.meter span { display: block; height: 100%; background: var(--accent); border-radius: 3px; }
button { font: inherit; cursor: pointer; border-radius: 8px; border: 1px solid var(--line);
  background: var(--surface); color: var(--ink); padding: 7px 12px; }
button:hover { border-color: var(--muted); }
:focus-visible { outline: 2px solid var(--focus); outline-offset: 2px; }
label.toggle { color: var(--ink-2); display: inline-flex; gap: 6px; align-items: center; }
article { background: var(--surface); border: 1px solid var(--line); border-radius: 12px;
  padding: 14px 16px; margin: 14px 0; }
article.current { border-color: var(--accent); }
.top { display: flex; gap: 10px; align-items: baseline; }
.num { color: var(--muted); font-variant-numeric: tabular-nums; }
h2 { font-size: 17px; margin: 0; flex: 1; }
.meta { color: var(--ink-2); margin: 4px 0 8px; }
.chip { display: inline-block; background: var(--chip); border-radius: 999px; padding: 1px 9px;
  margin: 2px 4px 2px 0; font-size: 13px; color: var(--ink-2); }
.excerpt { color: var(--ink-2); white-space: pre-line; margin: 0 0 10px; }
.grades { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
.grades button { min-width: 112px; }
.grades button[aria-pressed="true"][data-g="0"] { background: var(--g0); color: var(--bg);
  border-color: var(--g0); }
.grades button[aria-pressed="true"][data-g="1"] { background: var(--g1); color: var(--bg);
  border-color: var(--g1); }
.grades button[aria-pressed="true"][data-g="2"] { background: var(--g2); color: var(--bg);
  border-color: var(--g2); }
.grades a { margin-left: auto; }
.done { color: var(--ink-2); text-align: center; padding: 24px 0 48px; }
@media (max-width: 600px) {
  .grades button { flex: 1 1 0; min-width: 0; } .grades a { width: 100%; }
}
</style>
</head>
<body>
<header>
  <h1>Noter les offres · __PERSON__</h1>
  <p class="sub">__COUNT__ offres, mélangées, sans score. Raccourcis : <b>0</b> <b>1</b> <b>2</b>
    pour noter l'offre encadrée, <b>j</b> / <b>k</b> pour passer à la suivante / précédente.</p>
  <p class="scale"><b>2</b> je voudrais qu'on me la montre en tête · <b>1</b> pertinente en
    partie · <b>0</b> hors sujet. Juge l'adéquation à ton profil, pas le lieu ni le taux.</p>
</header>
<div class="bar"><div class="bar-inner">
  <div class="progress"><span id="progress"></span>
    <div class="meter"><span id="meter"></span></div></div>
  <label class="toggle"><input type="checkbox" id="todo"> à noter seulement</label>
  <button id="copy">Copier les notes</button>
</div></div>
<main id="list"></main>
<p class="done" id="done"></p>
<script>
const JOBS = __DATA__;
const KEY = "notes-__PERSON_KEY__";
let grades = {};
try { grades = Object.assign({}, __INITIAL__, JSON.parse(localStorage.getItem(KEY) || "{}")); }
catch (e) { grades = Object.assign({}, __INITIAL__); }
let current = 0;
const list = document.getElementById("list");
const ENTITIES = {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"};
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ENTITIES[c]);
const LABELS = ["0 · hors sujet", "1 · en partie", "2 · en tête"];

function save() { try { localStorage.setItem(KEY, JSON.stringify(grades)); } catch (e) {} }
function render() {
  const todo = document.getElementById("todo").checked;
  list.innerHTML = JOBS.map((j, i) => {
    if (todo && grades[j.url] !== undefined) return "";
    const chips = [j.canton, j.family, j.seniority, j.workload, j.language].filter(Boolean)
      .map(c => `<span class="chip">${esc(c)}</span>`).join("");
    const buttons = [0, 1, 2].map(g => `<button data-g="${g}" data-i="${i}"
      aria-pressed="${grades[j.url] === g}">${LABELS[g]}</button>`).join("");
    return `<article id="o${i}" class="${i === current ? "current" : ""}">
      <div class="top"><span class="num">${i + 1}</span><h2>${esc(j.title)}</h2></div>
      <p class="meta">${esc(j.company)} ${chips}</p>
      ${j.excerpt ? `<p class="excerpt">${esc(j.excerpt)}${j.more ? "…" : ""}</p>` : ""}
      <div class="grades">${buttons}
        <a href="${esc(j.url)}" target="_blank" rel="noopener">Voir l'annonce ↗</a></div>
    </article>`;
  }).join("");
  const n = JOBS.filter(j => grades[j.url] !== undefined).length;
  document.getElementById("progress").textContent = `${n} / ${JOBS.length} notées`;
  document.getElementById("meter").style.width = `${100 * n / JOBS.length}%`;
  document.getElementById("done").textContent = n === JOBS.length
    ? "Tout est noté : « Copier les notes », puis colle le résultat dans le chat." : "";
}
function grade(i, g) {
  grades[JOBS[i].url] = g; save(); current = Math.min(i + 1, JOBS.length - 1); render();
  document.getElementById("o" + current)?.scrollIntoView({block: "center", behavior: "smooth"});
}
list.addEventListener("click", e => {
  const b = e.target.closest("button[data-g]");
  if (b) grade(+b.dataset.i, +b.dataset.g);
});
document.addEventListener("keydown", e => {
  if (e.target.closest("input, textarea")) return;
  if (["0", "1", "2"].includes(e.key)) grade(current, +e.key);
  else if (e.key === "j" || e.key === "k") {
    current = Math.max(0, Math.min(JOBS.length - 1, current + (e.key === "j" ? 1 : -1)));
    render(); document.getElementById("o" + current)?.scrollIntoView({block: "center"});
  }
});
document.getElementById("todo").addEventListener("change", render);
document.getElementById("copy").addEventListener("click", async () => {
  const text = JSON.stringify(grades);
  try {
    await navigator.clipboard.writeText(text);
    document.getElementById("copy").textContent = "Copié ✓";
  } catch (e) { prompt("Copie ce texte :", text); }
});
render();
</script>
</body>
</html>
"""


def _workload(job: dict) -> str | None:
    lo, hi = job.get("workload_min"), job.get("workload_max")
    if not lo:
        return None
    return f"{lo} %" if lo == hi else f"{lo}-{hi} %"


def render(person: str, jobs: list[dict], judgments: dict[str, int]) -> str:
    """`jobs` dans l'ordre du pool ; les jugements existants sont pré-remplis."""
    data = [{"url": j["url"], "title": j["title"], "company": j["company"],
             "canton": j.get("canton"), "family": j.get("family"),
             "seniority": j.get("seniority"), "language": j.get("language"),
             "workload": _workload(j), "excerpt": (j.get("description") or "")[:EXCERPT],
             "more": len(j.get("description") or "") > EXCERPT} for j in jobs]
    initial = {j["url"]: judgments[j["url"]] for j in jobs if j["url"] in judgments}

    def embed(obj):
        return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")

    key = "".join(c for c in person if c.isalnum())
    return (TEMPLATE.replace("__PERSON_KEY__", key).replace("__PERSON__", html.escape(person))
            .replace("__COUNT__", str(len(jobs))).replace("__INITIAL__", embed(initial))
            .replace("__DATA__", embed(data)))
