"""Ligne de commande : uv run job-rec-ai <commande>.

argparse (bibliothèque standard) plutôt que typer ou click : zéro dépendance pour six
commandes, et rien de magique à comprendre.
"""

import argparse
import json
import logging
import sys
import time
from contextlib import nullcontext
from datetime import date
from pathlib import Path

from job_rec_ai import (
    annotation,
    benchmark,
    domains,
    evaluation,
    explorer,
    pipeline,
    recommend,
    storage,
)
from job_rec_ai.companies import DEFAULT_CSV, find, load_companies
from job_rec_ai.connectors import REGISTRY
from job_rec_ai.cv import DEFAULT_CV, read_cv
from job_rec_ai.http import PoliteClient

FIXTURES = Path("tests/fixtures")


def _cmd_crawl(args, con):
    with PoliteClient(delay=args.delay) as client:
        report = pipeline.crawl(con, load_companies(args.companies), client, only=args.company)
    for name, loaded, expired in report.ok:
        print(f"  ok      {name:<35} {loaded:>5} offres  ({expired} expirées)")
    for name, error in report.errors:
        print(f"  ERREUR  {name:<35} {error}")
    for name, expired in report.suspect:
        print(f"  ALERTE  {name:<35} {expired} offres disparues d'un coup : panne de l'ATS ?")
    print(f"\n{len(report.ok)} ok, {len(report.errors)} en erreur, "
          f"{len(report.skipped)} ignorées (sans connecteur : voir `boards`)")
    try:  # les logos ne doivent jamais faire échouer la collecte
        _resolve_domains(args, con)
    except Exception as exc:
        logging.getLogger(__name__).exception("résolution des domaines")
        print(f"\nDomaines : échec ({type(exc).__name__}: {exc}), réessai à la prochaine collecte")


def _resolve_domains(args, con) -> None:
    """Domaine web de chaque employeur (logos de DoxAI) : overrides, config, puis logo.dev."""
    started = time.perf_counter()
    companies = load_companies(args.companies)
    storage.upsert_companies(con, companies)
    overrides = domains.load_overrides(
        args.domains or Path(args.companies).with_name(domains.OVERRIDES_NAME))
    search = domains.BrandSearch.from_env()  # None sans LOGO_DEV_SECRET_KEY
    with search or nullcontext():
        result = domains.resolve(con, companies, overrides, search)
    print(f"\nDomaines : {result.fixed} de la config et des overrides, {result.reused} déjà "
          f"en cache, {len(result.found)} trouvés, {len(result.not_found)} sans match sûr, "
          f"{len(result.errors)} en erreur ({time.perf_counter() - started:.0f} s)")
    for name, domain in result.found:
        print(f"  trouvé   {name:<35} {domain}")
    for name in result.not_found:
        print(f"  aucun    {name}")
    for name, error in result.errors:
        print(f"  ERREUR   {name:<35} {error}")
    if result.skipped:
        print(f"  {len(result.skipped)} entreprise(s) sans domaine connu : recherche sautée "
              f"({domains.ENV_KEY} absente)")


def _cmd_resolve_domains(args, con):
    _resolve_domains(args, con)


def _cmd_boards(args, con):
    """Couverture : quels ATS couvrent combien d'entreprises ? → quel connecteur écrire."""
    verified = storage.verified_companies(con)
    by_ats: dict[str, list[str]] = {}
    blocked: list[str] = []
    for c in load_companies(args.companies):
        if c["blocked"]:  # rien à écrire : robots.txt, refus du site, jobboard…
            blocked.append(f"{c['company']} ({c['blocked']})")
            continue
        by_ats.setdefault(c["ats"] or "(inconnu)", []).append(
            c["company"] + ("" if c["company"] in verified else " ?"))
    for ats, names in sorted(by_ats.items(), key=lambda kv: -len(kv[1])):
        status = "connecteur ✓" if ats in REGISTRY else "—"
        print(f"{ats:<16} {len(names):>3}  {status:<12} {', '.join(names)}")
    print("\n« ? » = board pas encore vérifié par une collecte réussie")
    if blocked:
        print(f"\nExclues ({len(blocked)}) : " + " ; ".join(blocked))


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


def _cmd_quality(args, con):
    """Les anomalies, par source : une part élevée sur une seule source = parseur à revoir."""
    columns = [("empty_description", "desc. vide"),
               ("short_description", f"< {storage.SHORT_DESCRIPTION} car."),
               ("no_date", "sans date"), ("no_canton", "sans canton"),
               ("other_language", "ni fr ni en")]
    print(f"{'source':<16} {'actives':>7}" + "".join(f" {label:>12}" for _, label in columns))
    for row in storage.quality(con):
        print(f"{row['source']:<16} {row['active']:>7}"
              + "".join(f" {row[key]:>12.0%}" for key, _ in columns))
    if stopped := storage.interrupted_crawl(con):
        print(f"\nALERTE : la collecte du {stopped.started_at:%d.%m.%Y %H:%M} s'est "
              f"arrêtée en route après {len(stopped.done)} entreprises ; "
              f"{len(stopped.missing)} n'ont pas été recollectées depuis.")
        if stopped.in_progress:
            print(f"  en cours au moment de l'arrêt : {stopped.in_progress}")
        others = [n for n in stopped.missing if n != stopped.in_progress]
        print(f"  pas recollectées depuis : {', '.join(others) or '(aucune autre)'}")
        print("  leurs offres datent d'une collecte antérieure : relancer `crawl`")
    failing = storage.failing_companies(con)
    print(f"\n{len(failing)} entreprise(s) en échec ou suspecte(s) à la dernière collecte")
    for company, ats, status, error in failing:
        print(f"  {status:<8} {company:<30} ({ats}) {error or ''}")


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
    storage.upsert_companies(con, load_companies(args.companies))  # secteur, canton de repli
    print(f"{pipeline.replay(con)} offres rechargées depuis data/raw/")


def _cmd_backfill_markdown(args, con):
    started = time.perf_counter()
    archives, updated = pipeline.backfill_markdown(con)
    print(f"{updated} offres avec leur annonce en Markdown, depuis {archives} archives de "
          f"data/raw/ ({time.perf_counter() - started:.0f} s)")


def _cmd_explore(args, con):
    """Une page HTML autonome pour parcourir les offres actives (filtres, regroupements)."""
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(explorer.render(storage.active_jobs(con)), encoding="utf-8")
    print(f"{out} ({out.stat().st_size / 1e6:.1f} Mo) : à ouvrir dans un navigateur")


def _cmd_recommend(args, con):
    """Les offres les plus proches du CV (BM25), avec leur score."""
    ranked = recommend.rank(storage.jobs_for_ranking(con), read_cv(args.cv))
    for i, job in enumerate(ranked[:args.limit], 1):
        print(f"{i:>3}. {job['score']:6.1f}  {job['company']:<22.22} {job['title'][:58]:<58}"
              f"  [{job['family']} · {job['canton']}]")
        if args.urls:
            print(f"            {job['url']}")


def _private_set() -> evaluation.EvalSet | None:
    """Le jeu de Leif, créé au premier pooling à partir de data/private/ (CV, profil)."""
    path = evaluation.EVAL_DIRS[1] / "leif.json"
    if path.exists():
        return next(s for s in evaluation.load_sets() if s.path == path)
    queries = {name: str(p) for name, p in
               (("cv", DEFAULT_CV), ("profil", DEFAULT_CV.with_name("profil.md"))) if p.exists()}
    return evaluation.new_set(path, "leif", queries) if queries else None


def _cmd_eval(args, con):
    """Pooling + page d'annotation (--pool), import des notes (--import), métriques (défaut)."""
    if args.pool:
        sets = [s for s in [*evaluation.load_sets(evaluation.EVAL_DIRS[:1]), _private_set()] if s]
        for es in sets:
            # Pool et notes gardés même expirés : une offre du pool reste à noter
            corpus = evaluation.Corpus.of(
                storage.jobs_for_ranking(con, include=[*es.pool, *es.judgments]))
            es.pool, es.drawn = evaluation.build_pool(es, corpus)
            es.pooled_at = evaluation.today()
            es.save()
            by_url = {j["url"]: j for j in corpus.jobs}
            shown = [by_url[u] for u in es.pool if u in by_url]
            out = es.path.with_name(f"annoter-{es.person}.html")
            out.write_text(annotation.render(es.person, shown, es.judgments), encoding="utf-8")
            todo = sum(j["url"] not in es.judgments for j in shown)
            print(f"{es.person} : pool de {len(shown)} offres ({todo} à noter) → {out}")
        return
    if args.import_path:
        es = next((s for s in evaluation.load_sets() if s.person == args.person), None)
        if es is None:
            sys.exit(f"aucun jeu d'évaluation pour « {args.person} » (lancer `eval --pool`)")
        raw = json.loads(Path(args.import_path).read_text(encoding="utf-8"))
        try:
            grades = evaluation.validate_grades(raw)
        except ValueError as e:
            sys.exit(str(e))
        outside = sum(url not in es.pool for url in grades)
        es.judgments.update(grades)
        es.save()
        print(f"{es.person} : {len(grades)} notes importées, {len(es.judgments)} au total"
              + (f" ({outside} hors du pool)" if outside else ""))
        return
    for es in evaluation.load_sets():
        if not es.judgments:
            print(f"{es.person} : aucune note (lancer `eval --pool`, puis noter)")
            continue
        corpus = evaluation.Corpus.of(storage.jobs_for_ranking(con, include=list(es.judgments)))
        counts = evaluation.grade_counts(es)
        print(f"\n── {es.person} : {len(es.judgments)} offres notées "
              f"(2 : {counts[2]}, 1 : {counts[1]}, 0 : {counts[0]}) ; "
              f"{len(corpus.jobs)} offres classées")
        print(f"  {'méthode · requête':<26}{'P@10':>7}{'MRR':>7}{'nDCG@10':>9}{'jugées':>8}")
        rows = sorted(evaluation.evaluate(es, corpus), key=lambda r: -r.ndcg)
        for r in rows:
            print(f"  {r.run:<26}{r.precision:>7.2f}{r.mrr:>7.2f}{r.ndcg:>9.3f}{r.judged:>8.0%}")
        n, random_grades = evaluation.random_baseline(es)
        if n:
            print(f"  hasard ({n} offres tirées) : {n - random_grades[0]} notée(s) ≥ 1, "
                  f"{random_grades[2]} notée(s) 2 → P@10 attendue ≈ {1 - random_grades[0] / n:.2f}")


def _cmd_rederive(args, con):
    result = pipeline.rederive(con)
    print(f"{result.recalculated} offres recalculées, "
          f"{result.out_of_scope} sorties du périmètre (désactivées)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="job-rec-ai")
    parser.add_argument("--db", default=storage.DEFAULT_DB, type=Path)
    parser.add_argument("--companies", default=DEFAULT_CSV, type=Path)
    parser.add_argument("--domains", type=Path,
                        help=f"overrides des domaines (défaut : {domains.OVERRIDES_NAME} "
                             "à côté de --companies)")
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

    sub.add_parser("quality", help="contrôles qualité : champs vides, collectes en échec"
                   ).set_defaults(func=_cmd_quality)

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
    sub.add_parser("resolve-domains",
                   help="domaine web de chaque employeur (config, overrides, logo.dev)"
                   ).set_defaults(func=_cmd_resolve_domains)
    sub.add_parser("backfill-markdown",
                   help="annonces en Markdown depuis data/raw (sans réseau ni collecte)"
                   ).set_defaults(func=_cmd_backfill_markdown)
    p = sub.add_parser("recommend", help="les offres les plus proches d'un CV (BM25)")
    p.add_argument("--cv", default=DEFAULT_CV, type=Path, help="PDF, .txt ou .md")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--urls", action="store_true", help="afficher le lien de chaque offre")
    p.set_defaults(func=_cmd_recommend)
    p = sub.add_parser("eval", help="jeu d'évaluation : pooling, notes, métriques")
    p.add_argument("--pool", action="store_true",
                   help="construire le pool d'offres à noter et la page d'annotation")
    p.add_argument("--import", dest="import_path", metavar="JSON",
                   help="importer les notes copiées depuis la page d'annotation")
    p.add_argument("--person", default="leif", help="jeu visé par --import")
    p.set_defaults(func=_cmd_eval)
    sub.add_parser("rederive", help="recalculer langue, canton et classement").set_defaults(
        func=_cmd_rederive)

    p = sub.add_parser("explore", help="générer la page HTML qui regroupe les offres")
    p.add_argument("--out", default="data/offres.html", help="fichier produit")
    p.set_defaults(func=_cmd_explore)
    return parser


def main(argv: list[str] | None = None) -> None:
    # La console Windows écrit par défaut en cp1252 : « ✓ », « → » feraient planter print
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")
    con = storage.connect(args.db)
    try:
        args.func(args, con)
    finally:
        con.close()
