"""Ligne de commande : uv run job-rec-ai <commande>.

argparse (bibliothèque standard) plutôt que typer ou click : zéro dépendance pour six
commandes, et rien de magique à comprendre.
"""

import argparse
import json
import logging
from datetime import date
from pathlib import Path

from job_rec_ai import benchmark, pipeline, storage
from job_rec_ai.companies import DEFAULT_CSV, find, load_companies
from job_rec_ai.connectors import REGISTRY
from job_rec_ai.http import PoliteClient

FIXTURES = Path("tests/fixtures")


def _cmd_crawl(args, con):
    with PoliteClient(delay=args.delay) as client:
        report = pipeline.crawl(con, load_companies(args.companies), client, only=args.company)
    for name, loaded, expired in report.ok:
        print(f"  ok      {name:<35} {loaded:>5} offres  ({expired} expirées)")
    for name, error in report.errors:
        print(f"  ERREUR  {name:<35} {error}")
    print(f"\n{len(report.ok)} ok, {len(report.errors)} en erreur, "
          f"{len(report.skipped)} ignorées (sans connecteur : voir `boards`)")


def _cmd_boards(args, con):
    """Couverture : quels ATS couvrent combien d'entreprises ? → quel connecteur écrire."""
    verified = storage.verified_companies(con)
    by_ats: dict[str, list[str]] = {}
    for c in load_companies(args.companies):
        by_ats.setdefault(c["ats"] or "(inconnu)", []).append(
            c["company"] + ("" if c["company"] in verified else " ?"))
    for ats, names in sorted(by_ats.items(), key=lambda kv: -len(kv[1])):
        status = "connecteur ✓" if ats in REGISTRY else "—"
        print(f"{ats:<16} {len(names):>3}  {status:<12} {', '.join(names)}")
    print("\n« ? » = board pas encore vérifié par une collecte réussie")


def _print_counts(con, facet, limit):
    rows = storage.counts(con, facet, limit)
    total = sum(n for _, n in rows) or 1
    print(f"\n── {facet} ──")
    for value, n in rows:
        print(f"  {value:<38} {n:>6}  {'█' * round(40 * n / total)}")


def _cmd_stats(args, con):
    active, total = storage.totals(con)
    print(f"{active} offres actives ({total} vues au total)")
    for facet in args.facets or ["company", "family", "canton", "seniority", "language"]:
        _print_counts(con, facet, args.limit)


def _cmd_search(args, con):
    facets = {f: getattr(args, f) for f in storage.FACETS}
    rows = storage.search(con, text=args.text, since=args.since, min_workload=args.min_workload,
                          sort=args.sort, limit=args.limit, **facets)
    for r in rows:
        taux = f" {r['workload_min']}-{r['workload_max']}%" if r["workload_min"] else ""
        print(f"{str(r['posted_at'] or ''):<10}  {r['company']:<22.22} {r['title'][:60]:<60}"
              f"  [{r['family']} · {r['seniority']} · {r['canton']}{taux}]")
        if args.urls:
            print(f"            {r['url']}")
    print(f"\n{len(rows)} résultat(s)")


def _cmd_fixture(args, con):
    """Enregistre une VRAIE réponse d'ATS (réduite à quelques offres) comme fixture de test."""
    company = find(load_companies(args.companies), args.company)
    if reason := pipeline.skip_reason(company):
        raise SystemExit(f"{company['company']} : {reason}")
    with PoliteClient() as client:
        payload = pipeline.fetch_company(company, client)
    payload["postings"] = payload["postings"][: args.n]
    FIXTURES.mkdir(parents=True, exist_ok=True)
    path = FIXTURES / f"{company['ats']}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(payload['postings'])} offres réelles → {path}")


def _cmd_benchmark(args, con):
    keys = benchmark.credentials()
    tracked = [c["company"] for c in load_companies(args.companies)]
    ours = dict(storage.counts(con, "company", limit=None))
    with PoliteClient(delay=args.delay) as client:
        for where in args.where or benchmark.DEFAULT_WHERE:
            print(f"\n── Adzuna, top employeurs : {where} ──")
            print(f"  {'entreprise':<34} {'Adzuna':>7} {'nous':>6} {'rappel':>7}")
            for row in benchmark.compare(benchmark.top_companies(client, where, keys), ours,
                                         tracked):
                ours_txt = "non suivie" if row.ours is None else str(row.ours)
                recall = f"{row.recall:.0%}" if row.recall is not None else ""
                print(f"  {row.company:<34.34} {row.adzuna:>7} {ours_txt:>6} {recall:>7}")


def _cmd_replay(args, con):
    print(f"{pipeline.replay(con)} offres rechargées depuis data/raw/")


def _cmd_rederive(args, con):
    print(f"{pipeline.rederive(con)} offres recalculées")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="job-rec-ai")
    parser.add_argument("--db", default=storage.DEFAULT_DB, type=Path)
    parser.add_argument("--companies", default=DEFAULT_CSV, type=Path)
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("crawl", help="collecter les offres de toutes les entreprises")
    p.add_argument("--company", action="append", help="limiter à une entreprise (répétable)")
    p.add_argument("--delay", type=float, default=1.0, help="secondes entre 2 requêtes / hôte")
    p.set_defaults(func=_cmd_crawl)

    sub.add_parser("boards", help="couverture des ATS").set_defaults(func=_cmd_boards)

    p = sub.add_parser("stats", help="répartition des offres actives par facette")
    p.add_argument("facets", nargs="*", metavar="FACETTE",
                   help=f"parmi : {', '.join(storage.FACETS)}")
    p.add_argument("--limit", type=int, default=15)
    p.set_defaults(func=_cmd_stats)

    p = sub.add_parser("search", help="filtrer et trier les offres")
    for facet in storage.FACETS:
        p.add_argument(f"--{facet}")
    p.add_argument("--text", help="mot dans le titre ou la description")
    p.add_argument("--since", type=date.fromisoformat, help="publiée depuis (AAAA-MM-JJ)")
    p.add_argument("--min-workload", type=int, help="taux d'activité minimal (en %%)")
    p.add_argument("--sort", choices=list(storage.SORTS), default="recent")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--urls", action="store_true", help="afficher les liens")
    p.set_defaults(func=_cmd_search)

    p = sub.add_parser("fixture", help="enregistrer une vraie réponse d'ATS dans tests/fixtures")
    p.add_argument("company")
    p.add_argument("-n", type=int, default=5)
    p.set_defaults(func=_cmd_fixture)

    p = sub.add_parser("benchmark", help="couverture comparée à Adzuna (clé API requise)")
    p.add_argument("--where", action="append",
                   help=f"lieu Adzuna (répétable, défaut : {', '.join(benchmark.DEFAULT_WHERE)})")
    p.add_argument("--delay", type=float, default=1.0)
    p.set_defaults(func=_cmd_benchmark)

    sub.add_parser("replay", help="reconstruire la base depuis data/raw").set_defaults(
        func=_cmd_replay)
    sub.add_parser("rederive", help="recalculer langue, canton et classement").set_defaults(
        func=_cmd_rederive)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")
    con = storage.connect(args.db)
    try:
        args.func(args, con)
    finally:
        con.close()
