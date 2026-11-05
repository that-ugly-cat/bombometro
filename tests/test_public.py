"""Public-mode resource boundaries and deployment configuration contracts."""

import asyncio
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import httpx
import pytest
from fastapi import FastAPI

from deployment.caddy import block
from forecast import ForecastCache, ForecastError, UpstreamBudget, make_site
from settings import Settings, valid_host
from traffic import Admission, PublicGuard

ROOT = Path(__file__).resolve().parents[1]


def test_default_mode_is_lab(monkeypatch):
    for name in ("APP_MODE", "PUBLIC_HOST", "APP_REVISION"):
        monkeypatch.delenv(name, raising=False)
    assert Settings.from_env().mode == "lab"


@pytest.mark.parametrize("host", ["https://example.org", "example.org/path", "example.org:443",
    "*.example.org", "example.org\nother.test", "-bad.example", "bad-.example", ""])
def test_public_host_cannot_inject_configuration(host):
    assert not valid_host(host)
    with pytest.raises(ValueError): block(host, 8502)


def test_public_mode_requires_host_and_revision(monkeypatch):
    monkeypatch.setenv("APP_MODE", "public")
    monkeypatch.delenv("PUBLIC_HOST", raising=False)
    monkeypatch.delenv("APP_REVISION", raising=False)
    with pytest.raises(ValueError, match="PUBLIC_HOST"): Settings.from_env()
    monkeypatch.setenv("PUBLIC_HOST", "bombometro.example.org")
    with pytest.raises(ValueError, match="APP_REVISION"): Settings.from_env()
    monkeypatch.setenv("APP_REVISION", "1" * 40)
    assert Settings.from_env().mode == "public"
    monkeypatch.setenv("APP_MODE", "publci")
    with pytest.raises(ValueError, match="APP_MODE"): Settings.from_env()


def test_admission_refills_and_bounds_concurrency():
    now = [0]
    budget = Admission(burst=2, per_second=1, concurrent=1, clock=lambda: now[0])
    assert budget.enter() is None
    assert budget.enter() == 503
    budget.leave()
    assert budget.enter() is None
    budget.leave()
    assert budget.enter() == 429
    now[0] = 1
    assert budget.enter() is None
    budget.leave()
    assert budget.active == 0


def test_guard_health_remains_available_during_forecast_and_releases_slots():
    async def exercise():
        entered, release = asyncio.Event(), asyncio.Event()
        app = FastAPI()
        @app.get("/app")
        async def forecast_page():
            entered.set()
            await release.wait()
            return {"ok": True}
        @app.get("/healthz")
        async def health(): return {"ok": True}
        budget = Admission(concurrent=1)
        guarded = PublicGuard(app, budget)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=guarded), base_url="http://test") as client:
            first = asyncio.create_task(client.get("/app"))
            await asyncio.wait_for(entered.wait(), 1)
            assert (await client.get("/app")).status_code == 503
            assert (await client.get("/healthz")).status_code == 200
            assert (await client.post("/app")).status_code == 405
            assert (await client.get("/app?q=" + "x" * 2100)).status_code == 414
            release.set()
            assert (await first).status_code == 200
            assert budget.active == 0
    asyncio.run(exercise())


def test_guard_exception_does_not_leak_slot():
    async def exercise():
        async def broken(scope, receive, send): raise RuntimeError("test failure")
        budget = Admission()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=PublicGuard(broken, budget)), base_url="http://test") as client:
            with pytest.raises(RuntimeError): await client.get("/app")
        assert budget.active == 0
    asyncio.run(exercise())


def test_upstream_budget_minute_hour_day_and_reset():
    now = [90000]
    budget = UpstreamBudget(clock=lambda: now[0])
    for _ in range(30): budget.take()
    with pytest.raises(ForecastError, match="upstream_budget"): budget.take()
    now[0] += 61
    budget.take()
    budget.calls.clear()
    budget.calls.extend([now[0] - 120] * 300)
    with pytest.raises(ForecastError): budget.take()
    budget.calls.clear()
    budget.calls.extend([now[0] - 4000] * 2000)
    with pytest.raises(ForecastError): budget.take()
    now[0] += 86401
    budget.take()
    assert len(budget.calls) == 1


def test_fetch_contention_fails_fast_without_poisoning_cache():
    sample = json.loads((ROOT / "tests/fixtures/open_meteo.json").read_text())
    entered, release = Event(), Event()
    def fetch(site):
        entered.set()
        assert release.wait(3)
        return sample["forecast"], sample["pressure"]
    cache = ForecastCache(fetcher=fetch, lock_timeout=0.01)
    site = make_site("Grappa", "icon_eu")
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(cache.get, site)
        assert entered.wait(1)
        try:
            with pytest.raises(ForecastError, match="busy"): cache.get(site)
            assert not cache.entries
        finally:
            release.set()
        report = first.result()
    assert cache.get(site) is report


def test_no_more_than_two_cold_fetches():
    sample = json.loads((ROOT / "tests/fixtures/open_meteo.json").read_text())
    entered = [Event(), Event()]
    release = Event()
    def fetch(site):
        entered[0 if site.name == "Grappa" else 1].set()
        assert release.wait(3)
        return sample["forecast"], sample["pressure"]
    cache = ForecastCache(fetcher=fetch)
    with ThreadPoolExecutor(max_workers=2) as pool:
        tasks = [pool.submit(cache.get, make_site(name, "icon_eu")) for name in ("Grappa", "Cavallaria")]
        assert all(event.wait(1) for event in entered)
        try:
            with pytest.raises(ForecastError, match="busy"): cache.get(make_site("Meduno", "icon_eu"))
        finally:
            release.set()
        for task in tasks: task.result()


def test_public_application_in_clean_subprocess():
    script = '''
import json
import web
from pathlib import Path
from fastapi.testclient import TestClient
from forecast import ForecastCache
sample=json.loads(Path("tests/fixtures/open_meteo.json").read_text())
web.cache=ForecastCache(fetcher=lambda site:(sample["forecast"],sample["pressure"]))
with TestClient(web.app,base_url="https://bombometro.example.org") as c:
    h=c.get("/healthz")
    assert h.json()["mode"]=="public" and h.json()["revision"]=="1"*40
    for path in ("/","/app","/guide","/static/app.js","/robots.txt"):
        r=c.get(path)
        assert r.status_code==200 and not r.history, (path,r.status_code)
        assert r.headers["cache-control"]=="no-store"
        assert "unsafe-inline" not in r.headers["content-security-policy"]
        assert "sha256-" in r.headers["content-security-policy"]
    assert "PUBLIC / BETA" in c.get("/").text
    assert "LAB / 03" not in c.get("/").text
    assert c.get("/app",headers={"X-Borant-Sub":"forged","Authorization":"Bearer fake"}).status_code==200
    assert c.get("/healthz",headers={"Host":"evil.example.org"}).status_code==400
    assert c.post("/app").status_code==405
    assert c.get("/app?q="+"x"*2100).status_code==414
    assert c.get("/app/").status_code==404
    print("public-mode checks passed")
'''
    result = subprocess.run([sys.executable, "-c", script], cwd=ROOT, text=True,
                            capture_output=True, timeout=30,
                            env={**os.environ, "APP_MODE": "public", "PUBLIC_HOST": "bombometro.example.org", "APP_REVISION": "1" * 40})
    assert result.returncode == 0, result.stderr


def test_container_context_is_allowlisted_and_nonroot():
    dockerfile = (ROOT / "Dockerfile").read_text()
    ignore = (ROOT / ".dockerignore").read_text().splitlines()
    assert ignore[0] == "**"
    assert "COPY . ." not in dockerfile
    assert "USER 10001:10001" in dockerfile
    assert "--no-dev --no-install-project" in dockerfile
    for forbidden in ("!.env", "!.git/", "!runtime/", "!advisor.py", "!tests/"):
        assert forbidden not in ignore
    for required in ("!settings.py", "!traffic.py", "!static/", "!templates/"):
        assert required in ignore


def test_generated_caddy_is_public_and_loopback():
    config = block("bombometro.example.org", 8502)
    assert "reverse_proxy 127.0.0.1:8502" in config
    assert "forward_auth" not in config
    assert "header_up -X-Borant-*" in config
    assert "max_size 1KB" in config
    with pytest.raises(ValueError): block("bombometro.example.org", 80)


@pytest.mark.parametrize("complete,days,passes", [(23, [15], True), (119, [15]*5, True),
    (0, [0]*5, False), (30, [14, 14], False), (14, [14], False)])
def test_smoke_requires_complete_inputs_not_just_rendered_charts(complete, days, passes):
    from deployment.smoke import check_forecast_data
    metadata = json.dumps({"total_hours": 120, "complete_hours": complete,
                           "daytime_complete_hours": days})
    page = '<div class="chart-card"></div>' * 12 + f'<script type="application/json" id="forecast-availability">{metadata}</script>'
    if passes:
        assert check_forecast_data(page)["complete_hours"] == complete
    else:
        with pytest.raises(AssertionError): check_forecast_data(page)


def test_smoke_rejects_missing_availability_metadata():
    from deployment.smoke import check_forecast_data
    with pytest.raises(AssertionError): check_forecast_data('<div class="chart-card"></div>' * 12)
