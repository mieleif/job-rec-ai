import httpx
import pytest
from fake_ats import transport

from job_rec_ai.http import DisallowedByRobots, PoliteClient


def make_client(handler, sleeps):
    return PoliteClient(delay=1.0, transport=transport(handler), sleep=sleeps.append)


def test_respecte_robots_txt():
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /private\n")
        return httpx.Response(200, json={"ok": True})

    with make_client(handler, []) as client:
        assert client.get_json("https://x.example/public") == {"ok": True}
        with pytest.raises(DisallowedByRobots):
            client.get_json("https://x.example/private/jobs")


def test_robots_en_panne_on_s_abstient():
    with make_client(lambda r: httpx.Response(503), []) as client:
        assert not client.allowed("https://down.example/jobs")


def test_429_attend_retry_after_puis_reessaie(sleeps):
    calls = []

    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "7"})
        return httpx.Response(200, json={"ok": True})

    with make_client(handler, sleeps) as client:
        assert client.get_json("https://x.example/jobs") == {"ok": True}
    assert len(calls) == 2
    assert 7.0 in sleeps


def test_5xx_persistant_finit_par_echouer(sleeps):
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(502)

    with make_client(handler, sleeps) as client, pytest.raises(httpx.HTTPStatusError):
        client.get_json("https://x.example/jobs")
    assert [s for s in sleeps if s >= 2] == [2, 4, 8, 16]  # backoff exponentiel


def test_user_agent_identifiable():
    seen = []

    def handler(request):
        seen.append(request.headers["User-Agent"])
        return httpx.Response(404 if request.url.path == "/robots.txt" else 200, json={})

    with make_client(handler, []) as client:
        client.get_json("https://x.example/jobs")
    assert all("job-rec-ai" in ua and "github.com" in ua for ua in seen)
