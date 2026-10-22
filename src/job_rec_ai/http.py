"""Client HTTP « poli » : un seul endroit pour les règles de collecte responsable.

- user-agent identifiable (qui collecte, et où nous contacter) ;
- respect de robots.txt, lu une fois par hôte ;
- pause minimale entre deux requêtes vers le même hôte ;
- 429 (trop de requêtes) et 5xx : on attend (Retry-After si fourni, sinon backoff
  exponentiel 2 s, 4 s, 8 s…) puis on réessaie, un nombre limité de fois.

httpx plutôt que requests : même API, mais timeouts par défaut, HTTP/2, et un
MockTransport qui permet de tester tout ça sans réseau.
"""

import time
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

USER_AGENT = "job-rec-ai/0.1 (+https://github.com/mieleif/job-rec-ai)"
RETRY_STATUSES = {429, 500, 502, 503, 504}


class DisallowedByRobots(Exception):
    """robots.txt interdit cette URL à notre user-agent : on ne la demande pas."""


class PoliteClient:
    def __init__(self, delay: float = 1.0, max_retries: int = 4,
                 transport: httpx.BaseTransport | None = None, sleep=time.sleep):
        self.delay = delay
        self.max_retries = max_retries
        self._sleep = sleep  # injectable : les tests ne veulent pas vraiment attendre
        self._robots: dict[str, RobotFileParser] = {}
        self._last_request: dict[str, float] = {}
        self._client = httpx.Client(
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=30, follow_redirects=True, transport=transport,
        )

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._client.close()

    # --- règles de politesse -------------------------------------------------------------

    def allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            parser = RobotFileParser()
            response = self._send("GET", f"{origin}/robots.txt", check_robots=False)
            if response.status_code >= 500:
                # Serveur en panne : dans le doute, on s'abstient (RFC 9309)
                parser.disallow_all = True
            elif response.status_code >= 400:
                # Pas de robots.txt (404) : la convention est que tout est permis
                parser.parse([])
            else:
                parser.parse(response.text.splitlines())
            self._robots[origin] = parser
        return self._robots[origin].can_fetch(USER_AGENT, url)

    def _wait_turn(self, host: str) -> None:
        elapsed = time.monotonic() - self._last_request.get(host, float("-inf"))
        if elapsed < self.delay:
            self._sleep(self.delay - elapsed)
        self._last_request[host] = time.monotonic()

    # --- requêtes ------------------------------------------------------------------------

    def _send(self, method: str, url: str, check_robots: bool = True, **kwargs) -> httpx.Response:
        if check_robots and not self.allowed(url):
            raise DisallowedByRobots(url)
        host = urlsplit(url).netloc
        for attempt in range(self.max_retries + 1):
            self._wait_turn(host)
            response = self._client.request(method, url, **kwargs)
            if response.status_code not in RETRY_STATUSES or attempt == self.max_retries:
                return response
            self._sleep(_retry_after(response) or 2 ** (attempt + 1))
        raise AssertionError("unreachable")

    def get_json(self, url: str, **kwargs):
        response = self._send("GET", url, **kwargs)
        response.raise_for_status()
        return response.json()

    def post_json(self, url: str, payload: dict, **kwargs):
        response = self._send("POST", url, json=payload, **kwargs)
        response.raise_for_status()
        return response.json()


def _retry_after(response: httpx.Response) -> float | None:
    """Retry-After en secondes (la forme « date HTTP » est rare sur les API, on l'ignore)."""
    value = response.headers.get("Retry-After", "")
    # Plafonné à 5 min : un serveur qui demande d'attendre une heure, on y reviendra demain
    return min(float(value), 300.0) if value.isdigit() else None
