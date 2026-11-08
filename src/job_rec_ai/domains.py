"""Le domaine web de chaque employeur (« vitol.com », « coop.ch ») : DoxAI en tire le logo
(`https://img.logo.dev/<domaine>`).

Trois sources, de la plus sûre à la moins sûre ; la première qui répond gagne :

1. **override** : `company_domains.csv` (à côté de `companies.csv`), pour corriger une
   erreur de la recherche ; un domaine vide y veut dire « pas de logo » ;
2. **config** : la colonne `domain` de `companies.csv`, écrite à la main pour chaque employeur
   dont on est sûr (site carrière, tenant de l'ATS, nom) ;
3. **search** : l'API Brand Search de logo.dev, interrogée avec le nom de l'entreprise
   (clé secrète `LOGO_DEV_SECRET_KEY`, jamais dans l'API ni dans le navigateur). Un candidat
   n'est retenu que si son nom normalisé est EXACTEMENT celui de l'entreprise (accents, casse
   et formes juridiques « SA », « AG », « Sàrl »… ignorés) ; plusieurs domaines pour ce nom :
   le seul en .ch, sinon aucun. Mieux vaut pas de logo qu'un faux logo.

Le résultat vit en base (table `company_domains`, une ligne par nom normalisé) : chaque
entreprise est cherchée une seule fois ; un « pas trouvé » est revérifié après 30 jours, une
erreur de l'API n'est pas enregistrée (on réessaie à la collecte suivante). La résolution
tourne à la fin de la collecte nocturne (et par `job-rec-ai resolve-domains`), jamais pendant
une requête : l'API ne fait que lire la table.
"""

import csv
import logging
import os
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from job_rec_ai import storage
from job_rec_ai.http import USER_AGENT
from job_rec_ai.text import normalize

log = logging.getLogger(__name__)

SEARCH_URL = "https://api.logo.dev/v2/search"
ENV_KEY = "LOGO_DEV_SECRET_KEY"
RECHECK_AFTER = timedelta(days=30)  # un « pas trouvé » est redemandé au bout de 30 jours
OVERRIDES_NAME = "company_domains.csv"
OVERRIDE, CONFIG, SEARCH = "override", "config", "search"

# Formes juridiques retirées en fin de nom (« Nestlé S.A. » = « Nestlé »), et mots de liaison
# ignorés partout (« Procter & Gamble » = « Procter and Gamble »). « group », « groupe »
# restent : « Swatch Group » (le groupe) n'est pas « Swatch » (la marque de montres).
LEGAL_SUFFIXES = {"sa", "ag", "sarl", "gmbh", "ltd", "limited", "inc", "incorporated", "llc",
                  "plc", "corp", "corporation", "co", "sas", "srl", "spa", "bv", "nv", "kg",
                  "ab", "se", "holding"}
CONNECTORS = {"and", "et", "und"}

_DOMAIN = re.compile(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z](?:[a-z0-9-]*[a-z0-9])?")


def normalize_domain(value: str | None) -> str | None:
    """« https://www.Coop.ch/fr/jobs » → « coop.ch » ; None si ce n'est pas un nom de domaine.
    Ne retire que « www. » : les autres sous-domaines restent (pas de liste des suffixes
    publics ici ; la config et logo.dev donnent déjà des domaines nus)."""
    text = (value or "").strip().lower()
    text = re.sub(r"^[a-z][a-z0-9+.-]*://", "", text)
    text = re.split(r"[/?#]", text, maxsplit=1)[0].rsplit("@", 1)[-1].split(":")[0].rstrip(".")
    text = text.removeprefix("www.")
    return text if _DOMAIN.fullmatch(text) else None


def company_key(name: str) -> str:
    """Le nom d'une entreprise réduit à ce qui l'identifie : sans accents ni casse, sans
    parenthèses (« HFR (hôpital fribourgeois) » → « hfr »), sans « & / and / et / und » ni
    forme juridique finale. Clé du cache, et critère d'un « match sûr » de la recherche."""
    text = re.sub(r"\([^)]*\)", " ", normalize(name)).replace(".", "")
    words = [w for w in re.findall(r"[a-z0-9]+", text) if w not in CONNECTORS]
    if words and words[0] == "the":
        words = words[1:]
    core = list(words)
    while core and core[-1] in LEGAL_SUFFIXES:
        core.pop()
    return " ".join(core or words)


def search_query(name: str) -> str:
    """Le nom envoyé à logo.dev : sans la précision entre parenthèses, accents gardés."""
    return re.sub(r"\s*\([^)]*\)", "", name).strip() or name


def pick(name: str, candidates: list[dict]) -> str | None:
    """Le domaine d'un candidat dont le nom correspond exactement à `name` (après
    normalisation) ; s'ils sont plusieurs à des domaines différents, le seul en .ch ;
    sinon None (ambigu : on n'affiche rien plutôt qu'un faux logo)."""
    target = company_key(name)
    domains = list(dict.fromkeys(
        domain for c in candidates
        if isinstance(c, dict) and company_key(str(c.get("name") or "")) == target
        and (domain := normalize_domain(c.get("domain")))))
    if len(domains) == 1:
        return domains[0]
    swiss = [d for d in domains if d.endswith(".ch")]
    return swiss[0] if len(swiss) == 1 else None


def load_overrides(path: Path | str) -> dict[str, tuple[str, str | None]]:
    """company_domains.csv → {clé : (entreprise, domaine ou None)} ; fichier absent = rien.
    Colonnes : company, domain (vide = « pas de logo »), reason (pour mémoire)."""
    path = Path(path)
    if not path.exists():
        return {}
    overrides = {}
    with open(path, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            name, raw = (row.get("company") or "").strip(), (row.get("domain") or "").strip()
            if not name:
                continue
            domain = normalize_domain(raw)
            if raw and domain is None:
                raise SystemExit(f"{path} : domaine invalide pour {name!r} : {raw!r}")
            overrides[company_key(name)] = (name, domain)
    return overrides


# --- la recherche logo.dev ----------------------------------------------------------------------

class SearchError(Exception):
    """La recherche n'a pas abouti (réseau, 5xx, 429 persistant) : rien n'est mis en cache."""


class AuthError(SearchError):
    """Clé refusée (401/403) : inutile d'insister pour les autres entreprises."""


class BrandSearch:
    """Client de l'API Brand Search de logo.dev : séquentiel, une pause entre deux appels,
    un timeout, un seul nouvel essai (après Retry-After / RateLimit-Reset s'il y en a)."""

    def __init__(self, key: str, delay: float = 1.0, timeout: float = 10.0,
                 retry_wait: float = 5.0, transport: httpx.BaseTransport | None = None,
                 sleep=time.sleep):
        self.delay, self.retry_wait, self._sleep = delay, retry_wait, sleep
        self._last: float | None = None
        self._client = httpx.Client(
            headers={"Authorization": f"Bearer {key}", "User-Agent": USER_AGENT,
                     "Accept": "application/json"},
            timeout=timeout, transport=transport)

    @classmethod
    def from_env(cls, **kwargs) -> "BrandSearch | None":
        key = (os.environ.get(ENV_KEY) or "").strip()
        return cls(key, **kwargs) if key else None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._client.close()

    def _pause(self) -> None:
        if self._last is not None:
            wait = self.delay - (time.monotonic() - self._last)
            if wait > 0:
                self._sleep(wait)
        self._last = time.monotonic()

    def search(self, name: str) -> list[dict]:
        """Les candidats [{name, domain, …}] de logo.dev, le meilleur d'abord."""
        error = "?"
        for attempt in (1, 2):
            self._pause()
            wait = self.retry_wait
            try:
                response = self._client.get(SEARCH_URL,
                                            params={"q": search_query(name), "limit": 10})
            except httpx.HTTPError as exc:
                error = f"{type(exc).__name__}: {exc}"
            else:
                if response.status_code in (401, 403):
                    raise AuthError(f"HTTP {response.status_code} (clé {ENV_KEY} refusée)")
                if response.status_code == 200:
                    return _candidates(response)
                error = f"HTTP {response.status_code}"
                if response.status_code != 429 and response.status_code < 500:
                    break  # 400, 404… : redemander la même chose ne changera rien
                header = (response.headers.get("Retry-After")
                          or response.headers.get("RateLimit-Reset"))
                if header and header.strip().isdigit():
                    wait = min(float(header), 60.0)
            if attempt == 1:
                self._sleep(wait)
        raise SearchError(error)


def _candidates(response: httpx.Response) -> list[dict]:
    try:
        body = response.json()
    except ValueError as exc:
        raise SearchError(f"réponse illisible : {exc}") from exc
    data = body.get("data") if isinstance(body, dict) else body  # v2 : {"data": […]} ; v1 : […]
    if not isinstance(data, list):
        raise SearchError("réponse inattendue (pas de liste de candidats)")
    return [c for c in data if isinstance(c, dict)]


# --- la résolution ------------------------------------------------------------------------------

@dataclass
class Resolved:
    fixed: int = 0        # domaines de la config et des overrides (re)écrits
    reused: int = 0       # entreprises déjà résolues par la recherche (cache)
    found: list[tuple[str, str]] = field(default_factory=list)  # (entreprise, domaine)
    not_found: list[str] = field(default_factory=list)  # aucun candidat sûr : null en cache
    errors: list[tuple[str, str]] = field(default_factory=list)  # réessayées la prochaine fois
    skipped: list[str] = field(default_factory=list)  # pas de clé : recherche sautée


def resolve(con, companies: list[dict], overrides: dict[str, tuple[str, str | None]],
            search: BrandSearch | None, now: datetime | None = None) -> Resolved:
    """Met à jour la table company_domains pour les entreprises suivies et celles des offres
    actives. Sans `search` (pas de clé), seules la config et les overrides sont écrits."""
    now = now or datetime.now(UTC).replace(tzinfo=None)
    result = Resolved()

    fixed: dict[str, tuple[str, str | None, str]] = {}
    for company in companies:
        if company.get("domain"):
            fixed[company_key(company["company"])] = (company["company"], company["domain"],
                                                      CONFIG)
    for key, (name, domain) in overrides.items():
        fixed[key] = (name, domain, OVERRIDE)
    storage.save_domains(con, [{"company_key": key, "company": name, "domain": domain,
                                "origin": origin, "checked_at": now}
                               for key, (name, domain, origin) in fixed.items()])
    result.fixed = len(fixed)

    cache = storage.domain_cache(con)
    # Un domaine de config ou d'override retiré du fichier : l'entreprise repasse à la recherche
    storage.delete_domains(con, [k for k, row in cache.items()
                                 if row["origin"] != SEARCH and k not in fixed])

    todo: dict[str, str] = {}  # clé → nom à chercher
    for name in storage.active_companies(con):
        key = company_key(name)
        if key in fixed or key in todo:
            continue
        row = cache.get(key)
        if row and row["origin"] == SEARCH and (
                row["domain"] or now - row["checked_at"] < RECHECK_AFTER):
            result.reused += 1
            continue
        todo[key] = name

    if search is None:
        result.skipped = list(todo.values())
        return result
    pending = list(todo.items())
    for i, (key, name) in enumerate(pending):
        try:
            domain = pick(name, search.search(name))
        except AuthError as exc:  # la clé ne marchera pas mieux pour les suivantes
            log.warning("logo.dev : %s ; recherche arrêtée", exc)
            result.errors += [(n, str(exc)) for _, n in pending[i:]]
            break
        except SearchError as exc:
            log.warning("logo.dev : %s : %s", name, exc)
            result.errors.append((name, str(exc)))
            continue
        storage.save_domains(con, [{"company_key": key, "company": name, "domain": domain,
                                    "origin": SEARCH, "checked_at": now}])
        if domain:
            result.found.append((name, domain))
        else:
            result.not_found.append(name)
    return result
