"""Connecteur Taleo (Oracle) : l'ATS historique des organisations internationales (OMS, OMPI).

Un employeur a une ou plusieurs « career sections » : https://<hôte>/careersection/<section>/
jobsearch.ftl. La page de recherche est une application JavaScript qui interroge :
    POST /careersection/rest/jobboard/searchjobs?portal=<n°>   liste paginée (25 par page)
    GET  /careersection/<section>/jobdetail.ftl?job=<n°>       annonce (HTML + JavaScript)
Le numéro de portail se lit dans la page de recherche. Les colonnes de la liste dépendent
de la configuration de chaque employeur : la réponse indique laquelle est le titre
(linkedColumn) et lesquelles sont les lieux (locationsColumns). Dans l'annonce, les champs
sont passés à un appel JavaScript (api.fillList(…, 'descRequisition', [...])) : les textes
longs y sont du HTML encodé en URL ; la date d'ouverture précède celle de clôture. On
n'archive que cette liste de champs.
"""

import json
import re
from datetime import date, datetime
from urllib.parse import unquote

from job_rec_ai.connectors.base import (
    LocationFilter,
    build_jobs,
    envelope,
    get_html_or_skip,
)
from job_rec_ai.http import PoliteClient
from job_rec_ai.models import Job
from job_rec_ai.text import clean_html

MAX_PAGES = 100  # garde-fou
_BOARD = re.compile(r"^(https://[^/]+)/careersection/([^/]+)/")
_PORTAL = re.compile(r"portalNo:\s*'(\d+)'")
_FIELDS = re.compile(r"api\.fillList\('requisitionDescriptionInterface',\s*'descRequisition',"
                     r"\s*\[(.*?)\]\);", re.S)
_JS_STRING = re.compile(r"'((?:[^'\\]|\\.)*)'")
_JS_ESCAPE = re.compile(r"\\(u[0-9a-fA-F]{4}|x[0-9a-fA-F]{2}|.)", re.S)
_JS_CONTROLS = {"n": "\n", "t": "\t", "r": "\r"}
# « 27-Oct-2026 » (OMPI) ou « Nov 4, 2026, 10:56:17 AM » (OMS)
_DATES = ((re.compile(r"^\d{1,2}-[A-Z][a-z]{2}-\d{4}"), "%d-%b-%Y"),
          (re.compile(r"^[A-Z][a-z]{2} \d{1,2}, \d{4}"), "%b %d, %Y"))
# Les en-têtes qu'envoie la page de recherche ; sans eux, le serveur répond 500
_HEADERS = {"X-Requested-With": "XMLHttpRequest", "tz": "GMT+01:00", "tzname": "Europe/Zurich"}
_FILTERS = ("POSTING_DATE", "LOCATION", "JOB_FIELD", "JOB_TYPE", "JOB_SCHEDULE", "JOB_LEVEL")


def _search(page_no: int) -> dict:
    """Le corps d'une recherche sans critère (toutes les offres), page par page."""
    empty = [{"id": f, "selectedValues": []} for f in _FILTERS]
    return {"multilineEnabled": True,
            "sortingSelection": {"sortBySelectionParam": "3", "ascendingSortingOrder": "false"},
            "fieldData": {"fields": {"KEYWORD": "", "LOCATION": ""}, "valid": True},
            "filterSelectionParam": {"searchFilterSelections": empty},
            "advancedSearchFiltersSelectionParam": {"searchFilterSelections": empty},
            "pageNo": page_no}


def locations_of(row: dict) -> list[str]:
    """Les colonnes de lieu contiennent une liste JSON : « ["Switzerland-Geneva"] »."""
    places = []
    for index in row.get("locationsColumns") or []:
        value = row["column"][index]
        try:
            places += json.loads(value)
        except (TypeError, ValueError):
            places.append(value)
    return [p for p in places if p]


def _js_unescape(text: str) -> str:
    """Les échappements d'une chaîne JavaScript : \' \n è…"""
    def decode(match: re.Match) -> str:
        code = match.group(1)
        if len(code) > 1:  # \uXXXX ou \xXX
            return chr(int(code[1:], 16))
        return _JS_CONTROLS.get(code, code)

    return _JS_ESCAPE.sub(decode, text)


def description_fields(html: str) -> list[str] | None:
    """Les champs de l'annonce, tels que passés à api.fillList ; None si absents."""
    match = _FIELDS.search(html)
    if not match:
        return None
    return [_js_unescape(s) for s in _JS_STRING.findall(match.group(1))]


def posted_on(fields: list[str]) -> date | None:
    """La première date des champs : l'ouverture du poste (la clôture vient après)."""
    for field in fields:
        for pattern, fmt in _DATES:
            if found := pattern.match(field):
                try:
                    return datetime.strptime(found.group(0), fmt).date()
                except ValueError:
                    continue
    return None


class TaleoConnector:
    name = "taleo"

    def fetch(self, board: str, company: str, client: PoliteClient,
              keep: LocationFilter) -> dict:
        match = _BOARD.match(board)
        if not match:
            raise ValueError(f"career section Taleo introuvable dans {board!r}")
        host, section = match.groups()
        portal = _PORTAL.search(client.get_html(board))
        if not portal:
            raise ValueError(f"numéro de portail introuvable dans {board}")
        search = f"{host}/careersection/rest/jobboard/searchjobs"

        # La taille des pages est propre à chaque career section : on compte les offres
        # reçues jusqu'au total annoncé, sans supposer 25 par page
        rows, total = [], 0
        for page_no in range(1, MAX_PAGES + 1):
            data = client.post_json(search, _search(page_no), headers=_HEADERS,
                                    params={"lang": "en", "portal": portal.group(1)})
            batch = data.get("requisitionList", [])
            rows += batch
            total = total or data.get("pagingData", {}).get("totalCount", 0)
            if not batch or len(rows) >= total:
                break

        postings = []
        for row in rows:
            if not any(keep(place) for place in locations_of(row)):
                continue
            url = f"{host}/careersection/{section}/jobdetail.ftl?job={row['contestNo']}&lang=en"
            raw = get_html_or_skip(client, url)
            fields = description_fields(raw) if raw else None
            if fields is not None:
                postings.append({**row, "url": url, "fields": fields})
        return envelope(self.name, company, board, postings)

    def parse(self, payload: dict) -> list[Job]:
        def to_fields(row: dict) -> dict:
            # Les textes longs (description, profil…) sont du HTML encodé en URL (%3Cp%3E),
            # précédé du marqueur « !*! » de Taleo
            texts = [clean_html(unquote(f).replace("!*!", "")) for f in row["fields"]
                     if "%3C" in f]
            return {
                "title": row["column"][row.get("linkedColumn", 0)],
                "url": row["url"],
                "location": " / ".join(locations_of(row)),
                "description": " ".join(texts),
                "posted_at": posted_on(row["fields"]),
                "source_id": row["contestNo"],
            }

        return build_jobs(payload, to_fields)
