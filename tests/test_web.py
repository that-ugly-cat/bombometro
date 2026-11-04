"""Public-data fixture, core parity and the actual rendered request surface."""

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
import requests
from fastapi.testclient import TestClient

import forecast
import web
from charts import day_charts, segments
from core import SITE_PRESETS, run_pipeline
from forecast import ForecastCache, ForecastError, build_report, make_site


@pytest.fixture
def sample():
    return json.loads((Path(__file__).parent / "fixtures/open_meteo.json").read_text())


@pytest.fixture
def site():
    return make_site("Grappa", "icon_eu")


@pytest.fixture
def client(monkeypatch, sample):
    monkeypatch.setattr(web, "cache", ForecastCache(
        fetcher=lambda s: (sample["forecast"], sample["pressure"])))
    with TestClient(web.app) as client:
        yield client


@pytest.mark.parametrize("site_name", list(SITE_PRESETS))
def test_complete_data_matches_original_core(sample, site_name):
    site = make_site(site_name, "icon_eu")
    original = run_pipeline(site, 5, sample["forecast"], sample["pressure"])
    guarded = build_report(site, sample["forecast"], sample["pressure"])
    assert not guarded["hours"][0]["complete"]  # No previous-hour trend input.
    for old, new in zip(original["evaluated"][1:], guarded["hours"][1:]):
        assert new["complete"]
        assert {k: new[k] for k in old} == old
    for day, old in original["summaries"].items():
        assert {k: guarded["summaries"][day][k] for k in old} == old


@pytest.mark.parametrize("key", forecast.REQUIRED)
def test_missing_scoring_input_never_gets_a_score(sample, site, key):
    ts = sample["forecast"]["hourly"]["time"][12]
    if key == "delta_p_foehn":
        sample["pressure"][ts][key] = None
    else:
        sample["forecast"]["hourly"][key][12] = None
    report = build_report(site, sample["forecast"], sample["pressure"])
    hour = report["hours"][12]
    assert not hour["complete"]
    assert key in hour["missing"]
    assert hour["fly_score"] is None
    assert "potential_score" not in hour
    assert report["summaries"][ts[:10]]["verdict"] == "incomplete data"
    assert report["summaries"][ts[:10]]["best_window"] is None


def test_previous_missing_wind_blocks_trend_score(sample, site):
    sample["forecast"]["hourly"]["wind_gusts_10m"][11] = None
    report = build_report(site, sample["forecast"], sample["pressure"])
    assert "previous:wind_gusts_10m" in report["hours"][12]["missing"]
    assert report["hours"][13]["complete"]


def test_missing_optional_diagnostic_is_a_gap_not_zero(sample, site):
    sample["forecast"]["hourly"]["freezing_level_height"][12] = None
    report = build_report(site, sample["forecast"], sample["pressure"])
    assert report["hours"][12]["complete"]
    plots = day_charts(report["hours"][6:21])
    freezing = next(c for c in plots if c["title"] == "Freezing level")
    assert freezing["lines"][0]["values"][6] is None
    assert len(freezing["lines"][0]["segments"]) == 2


def test_short_arrays_and_nonfinite_values_are_missing(sample, site):
    sample["forecast"]["hourly"]["wind_speed_10m"] = [float("nan")] * 12
    report = build_report(site, sample["forecast"], sample["pressure"])
    assert not any(h["complete"] for h in report["hours"])


@pytest.mark.parametrize("mutation", ["duplicate", "gap", "empty", "invalid"])
def test_malformed_time_axis_rejected(sample, site, mutation):
    times = sample["forecast"]["hourly"]["time"]
    if mutation == "duplicate": times[12] = times[11]
    elif mutation == "gap": times.pop(12)
    elif mutation == "empty": times.clear()
    else: times[12] = "not a timestamp"
    with pytest.raises(ForecastError, match="invalid_data"):
        build_report(site, sample["forecast"], sample["pressure"])


def test_cache_keys_ttl_and_coalescing(sample, site):
    calls = []
    now = [0]
    def fetch(s):
        calls.append((s.name, s.model))
        return sample["forecast"], sample["pressure"]
    cache = ForecastCache(fetcher=fetch, clock=lambda: now[0])
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: cache.get(site), range(4)))
    assert all(r is results[0] for r in results)
    assert len(calls) == 1
    cache.get(make_site("Cavallaria", "icon_eu"))
    cache.get(make_site("Grappa", "ecmwf_ifs"))
    assert len(calls) == 3
    now[0] = 1801
    cache.get(site)
    assert len(calls) == 4


def test_failed_refresh_never_serves_stale_data(sample, site):
    now = [0]
    calls = []
    def fetch(s):
        calls.append(1)
        if len(calls) > 1: raise ForecastError("unreachable")
        return sample["forecast"], sample["pressure"]
    cache = ForecastCache(fetcher=fetch, clock=lambda: now[0])
    cache.get(site)
    now[0] = 1801
    for _ in range(2):
        with pytest.raises(ForecastError, match="unreachable"):
            cache.get(site)
    assert len(calls) == 2
    now[0] = 1862
    with pytest.raises(ForecastError): cache.get(site)
    assert len(calls) == 3


def test_routes_and_rendered_form(client, sample):
    assert client.get("/healthz").json()["service"] == "bombometro"
    for path in ("/", "/guide", "/app", "/app?site=Cavallaria&model=icon_eu"):
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert "Traceback" not in response.text
    response = client.get("/app", params={
        "site": "Grappa", "model": "icon_eu", "day": sample["forecast"]["hourly"]["time"][0][:10]})
    assert response.status_code == 200
    assert 'name="site"' in response.text and 'name="model"' in response.text
    assert response.text.count('class="card chart-card"') == 12
    assert response.text.count('class="card hour-detail"') == 15
    assert "Innsbruck" in response.text
    assert "/static/style.css?v=" in response.text


@pytest.mark.parametrize("query", ["site=unknown", "model=unknown", "day=bad",
    "day=2026-13-52", "site=%3Cscript%3Ealert(1)%3C/script%3E", "site=" + "a" * 41])
def test_invalid_selection_is_html_not_a_traceback(client, query):
    r = client.get("/app?" + query)
    assert r.status_code == 422
    assert r.headers["content-type"].startswith("text/html")
    assert "<script>alert(1)</script>" not in r.text


def test_network_failure_is_explained(monkeypatch, client):
    def fail(s): raise ForecastError("unreachable")
    monkeypatch.setattr(web, "cache", ForecastCache(fetcher=fail))
    r = client.get("/app")
    assert r.status_code == 503
    assert "No substitute data" in r.text
    assert 'name="model"' in r.text
    assert 'class="day-grid"' not in r.text


def test_request_timeout_becomes_error_code(monkeypatch):
    def fail(*args, **kwargs): raise requests.Timeout("sensitive URL")
    monkeypatch.setattr(forecast.requests, "get", fail)
    with pytest.raises(ForecastError, match="^unreachable$"):
        forecast.request_json({})


def test_pressure_join_is_timestamp_based(monkeypatch, sample, site):
    times = sample["forecast"]["hourly"]["time"]
    pressure = [
        {"hourly": {"time": times[:3], "pressure_msl": [1000, 1001, 1002]}},
        {"hourly": {"time": times[1:4], "pressure_msl": [1005, 1006, 1007]}},
    ]
    answers = iter([sample["forecast"], pressure])
    monkeypatch.setattr(forecast, "request_json", lambda params: next(answers))
    _, series = forecast.fetch_public(site)
    assert series[times[0]]["delta_p_foehn"] is None
    assert series[times[1]]["delta_p_foehn"] == 4
    assert series[times[3]]["delta_p_foehn"] is None


def test_chart_gap_segments():
    assert segments([1, None, 2, 3], lambda x: x, lambda y: y) == ["0.0,1.0", "2.0,2.0 3.0,3.0"]


def test_small_chart_axis_keeps_fractional_tick_labels(sample, site):
    report = build_report(site, sample["forecast"], sample["pressure"])
    plots = day_charts(report["hours"][6:21])
    for plot in plots:
        labels = [tick["value"] for tick in plot["ticks"]]
        assert len(set(labels)) == len(labels)


def test_missing_values_visible_in_rendered_page(client, sample, monkeypatch):
    sample["forecast"]["hourly"]["wind_speed_10m"][12] = None
    monkeypatch.setattr(web, "cache", ForecastCache(
        fetcher=lambda s: (sample["forecast"], sample["pressure"])))
    r = client.get("/app")
    assert r.status_code == 200
    assert "Incomplete data" in r.text
    assert "No score: wind_speed_10m" in r.text
    assert "13/15 complete hours" in r.text


def test_forecast_starting_at_six_has_no_invented_initial_trend(sample, site):
    sample["forecast"]["hourly"] = {k: v[6:] for k, v in sample["forecast"]["hourly"].items()}
    report = build_report(site, sample["forecast"], sample["pressure"])
    assert report["hours"][0]["missing"] == ["previous:hour"]
    assert report["summaries"][report["days"][0]]["verdict"] == "incomplete data"


def test_bad_metadata_does_not_crash_rendering(client, sample, monkeypatch):
    for key in ("latitude", "longitude", "elevation"):
        sample["forecast"][key] = "bad provider value"
    monkeypatch.setattr(web, "cache", ForecastCache(
        fetcher=lambda s: (sample["forecast"], sample["pressure"])))
    r = client.get("/app")
    assert r.status_code == 200
    assert "bad provider value" not in r.text


def test_no_window_does_not_display_a_fictitious_mean(client, sample, monkeypatch):
    sample["forecast"]["hourly"]["wind_gusts_10m"] = [80] * 24
    monkeypatch.setattr(web, "cache", ForecastCache(
        fetcher=lambda s: (sample["forecast"], sample["pressure"])))
    r = client.get("/app")
    assert "NO WINDOW" in r.text
    assert "No mean to report" in r.text
    assert "WINDOW MEAN" not in r.text


def test_slow_fetch_does_not_block_other_cached_selection(sample, site):
    from threading import Event
    entered, release = Event(), Event()
    def fetch(s):
        if s.name == "Cavallaria":
            entered.set()
            assert release.wait(3)
        return sample["forecast"], sample["pressure"]
    cache = ForecastCache(fetcher=fetch)
    cached = cache.get(site)
    with ThreadPoolExecutor(max_workers=2) as pool:
        slow = pool.submit(cache.get, make_site("Cavallaria", "icon_eu"))
        assert entered.wait(1)
        try:
            assert pool.submit(cache.get, site).result(timeout=1) is cached
        finally:
            release.set()
        slow.result()
