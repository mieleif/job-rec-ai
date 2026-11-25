"""Expérience M4 : les modèles d'embeddings comprennent-ils des termes nés après eux ?

Cosinus entre des paires de même sens contenant des termes récents (MCP, vibe coding), des
témoins sans terme récent (FR/FR, FR/EN, FR/DE) et des paires qui donnent l'échelle (sens
opposé, sans rapport, piège lexical). Les valeurs absolues ne se comparent pas d'un modèle à
l'autre (chacun tasse ses cosinus à sa façon) : on lit la position dans l'échelle du modèle.

    uv run --env-file .env --group notebook python experiments/date_de_coupure.py
"""

import sys
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt

from job_rec_ai import embeddings

matplotlib.use("Agg")

RECENT, CONTROL, SCALE = "termes récents, même sens", "témoin, même sens", "échelle"
PAIRS = [
    (RECENT, "MCP / Model Context Protocol", "Développeur MCP et agents IA",
     "Intégration d'outils pour LLM via Model Context Protocol"),
    (RECENT, "vibe coding / dév. assisté par IA", "vibe coding avec Claude Code",
     "développement assisté par IA"),
    (CONTROL, "FR / FR", "Développeur logiciel, applications web",
     "Programmeur informatique, sites internet"),
    (CONTROL, "FR / EN", "Infirmière en soins intensifs", "Intensive care nurse"),
    (CONTROL, "FR / DE", "Vendeur dans le commerce de détail", "Verkäufer im Detailhandel"),
    (SCALE, "sens opposé", "Poste senior, dix ans d'expérience exigés",
     "Poste débutant, aucune expérience demandée"),
    (SCALE, "sans rapport", "Développeur MCP et agents IA", "Infirmière en soins intensifs"),
    (SCALE, "piège lexical (codage)", "vibe coding avec Claude Code",
     "codage médical des séjours hospitaliers"),
]
COLORS = {RECENT: "#2a78d6", CONTROL: "#eb6834", SCALE: "#898781"}
INK, INK2, LINE = "#0b0b0b", "#52514e", "#e6e5e1"


def cosines(client) -> dict[str, list[float]]:
    texts = [t for _, _, a, b in PAIRS for t in (a, b)]
    out = {}
    for name, model in embeddings.EMBEDDERS.items():
        v = client.embed_documents(model, texts)  # symétrique : pas d'instruction de requête
        out[name] = [float(v[2 * i] @ v[2 * i + 1]) for i in range(len(PAIRS))]
    return out


def plot(results: dict[str, list[float]], path: Path) -> None:
    fig, axes = plt.subplots(1, len(results), figsize=(11, 4.2), sharey=True, facecolor="#fcfcfb")
    rows = range(len(PAIRS))
    for ax, (name, values) in zip(axes, results.items()):
        ax.set_facecolor("#fcfcfb")
        for y in rows:
            ax.plot([0, values[y]], [y, y], color=LINE, lw=2, zorder=1)
            ax.scatter(values[y], y, s=64, color=COLORS[PAIRS[y][0]], zorder=2)
            ax.annotate(f"{values[y]:.2f}", (values[y], y), xytext=(8, 0), color=INK2,
                        textcoords="offset points", va="center", fontsize=9)
        ax.set_title(name, loc="left", color=INK, fontsize=11)
        ax.set_xlim(min(0, min(values)) - 0.02, 1.18)
        ax.set_xticks([0, 0.5, 1])
        ax.tick_params(length=0, colors=INK2, labelsize=9)
        for side in ax.spines.values():
            side.set_visible(False)
        ax.axvline(0, color=LINE, lw=1)
    axes[0].set_yticks(list(rows), [label for _, label, *_ in PAIRS])
    axes[0].invert_yaxis()
    handles = [plt.Line2D([], [], marker="o", ls="", ms=8, color=c, label=k)
               for k, c in COLORS.items()]
    fig.legend(handles=handles, loc="lower center", ncol=3, frameon=False, labelcolor=INK2)
    fig.suptitle("Cosinus par paire de textes", x=0.01, ha="left", color=INK, fontsize=13)
    fig.tight_layout(rect=(0, 0.07, 1, 0.97))
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=160)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    client = embeddings.Client.from_env()
    if client is None:
        sys.exit("INFOMANIAK_API_TOKEN absente")
    with client:
        results = cosines(client)
    print(f"{'paire':<36}" + "".join(f"{n:>10}" for n in results))
    for i, (_, label, *_) in enumerate(PAIRS):
        print(f"{label:<36}" + "".join(f"{v[i]:>10.3f}" for v in results.values()))
    out = Path(__file__).parents[1] / "docs/img/m4-date-de-coupure.png"
    plot(results, out)
    print(out)
