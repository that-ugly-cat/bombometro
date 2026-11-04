"""Public-data fixture, core parity and the actual rendered request surface."""

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
import requests
from fastapi.testclient import TestClient

import forecast
import web
from charts import day_charts, segments, wind_table, wind_color
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


def test_wind_table_levels_direction_and_speed(sample, site):
    report = build_report(site, sample["forecast"], sample["pressure"])
    hours = report["hours"][6:21]
    rows = wind_table(hours, site)
    assert [r["label"] for r in rows] == ["700 hPa", "800 hPa", "850 hPa", "925 hPa", "Gusts", "10 m wind"]
    assert all(len(r["cells"]) == 15 for r in rows)
    assert rows[0]["cells"][0]["speed"] == hours[0]["raw"]["wind_speed_700hPa"]
    assert rows[0]["cells"][0]["direction"] == hours[0]["raw"]["wind_direction_700hPa"]
    assert rows[4]["cells"][0]["speed"] == hours[0]["raw"]["wind_gusts_10m"]
    assert not rows[4]["cells"][0]["has_direction"]


def test_wind_table_preserves_calm_and_unknown_separately(site):
    rows = wind_table([{"raw": {"wind_speed_700hPa": 0, "wind_direction_700hPa": 0,
                               "wind_speed_850hPa": 15}}], site)
    assert rows[0]["cells"][0] == {"speed": 0, "direction": 0, "compass": "N", "color_class": "wind-heat wind-range-0 wind-mix-0", "has_direction": True}
    assert rows[1]["cells"][0]["speed"] is None
    assert rows[1]["cells"][0]["color_class"] == "wind-unknown"
    assert rows[2]["cells"][0]["compass"] is None
    assert rows[2]["cells"][0]["color_class"] == "wind-heat wind-range-1 wind-mix-5"


@pytest.mark.parametrize("speed,expected", [(None, "wind-unknown"), (0, "wind-heat wind-range-0 wind-mix-0"),
    (10, "wind-heat wind-range-1 wind-mix-5"), (19.99, "wind-heat wind-range-2 wind-mix-9"),
    (20, "wind-heat wind-range-2 wind-mix-10"), (100, "wind-heat wind-range-2 wind-mix-10")])
def test_wind_heat_scale_endpoints(speed, expected):
    assert wind_color(speed, 20) == expected


def test_wind_heat_scale_uses_each_rows_configured_limit(site):
    hours = [{"raw": {"wind_speed_700hPa": 25, "wind_speed_925hPa": 25, "wind_gusts_10m": 25}}]
    rows = wind_table(hours, site)
    assert [r["limit"] for r in rows] == [60, 35, 30, 25, 28, 20]
    assert rows[3]["cells"][0]["color_class"] == wind_color(25, 25)
    assert rows[0]["cells"][0]["color_class"] != rows[3]["cells"][0]["color_class"]
    assert rows[4]["cells"][0]["color_class"] == wind_color(25, 28)


def test_tooltip_values_match_plots_and_distinguish_veto(sample, site):
    sample["forecast"]["hourly"]["wind_gusts_10m"][12] = 80
    sample["forecast"]["hourly"]["wind_speed_700hPa"][13] = None
    report = build_report(site, sample["forecast"], sample["pressure"])
    plots = day_charts(report["hours"][6:21])
    for plot in plots:
        assert len(plot["hover"]) == 15
        for i, hover in enumerate(plot["hover"]):
            assert hover["time"] == f"{i + 6:02}:00"
            assert len(hover["readings"]) == len(plot["lines"])
            for reading, line in zip(hover["readings"], plot["lines"]):
                if line["values"][i] is not None:
                    assert reading["value"].startswith(f'{line["values"][i]:.1f}')
    assert plots[0]["hover"][6]["readings"][0]["value"] == "Veto"
    assert "Veto:" in plots[0]["hover"][6]["status"]
    assert plots[0]["hover"][7]["readings"][0]["value"] == "—"
    assert plots[0]["hover"][7]["status"] == "Scoring inputs incomplete"
    wind = next(p for p in plots if p["title"] == "Wind by level")
    assert "°" in wind["hover"][0]["readings"][0]["value"]
    assert "°" not in wind["hover"][0]["readings"][1]["value"]  # Gusts have no separate direction.


def test_wind_table_and_tooltip_data_rendered(client):
    import re
    r = client.get("/app")
    assert 'class="table wind-table"' in r.text
    assert '<th scope="row">700 hPa' in r.text
    assert '<th scope="col">20:00</th>' in r.text
    ids = re.findall(r'id="(chart-tooltip-\d+)"', r.text)
    assert len(ids) == len(set(ids)) == 12
    blobs = re.findall(r'<script type="application/json" class="chart-hover-data">(.*?)</script>', r.text)
    assert len(blobs) == 12
    assert all(len(json.loads(blob)["hours"]) == 15 for blob in blobs)


@pytest.mark.parametrize("direction,compass", [(0, "N"), (90, "E"), (180, "S"), (270, "W")])
def test_wind_arrows_point_downwind(client, sample, monkeypatch, direction, compass):
    sample["forecast"]["hourly"]["wind_direction_700hPa"] = [direction] * 24
    sample["forecast"]["hourly"]["wind_speed_700hPa"] = [10] * 24
    monkeypatch.setattr(web, "cache", ForecastCache(
        fetcher=lambda s: (sample["forecast"], sample["pressure"])))
    text = client.get("/app").text
    # Base path points down (towards south). Clockwise rotation by the wind-from
    # bearing gives N -> south, E -> west, S -> north and W -> east.
    assert f'd="M12 4 V20 M6 14 L12 20 L18 14" transform="rotate({direction:.1f} 12 12)"' in text
    assert f'title="From {compass} ({direction}°); arrow points downwind"' in text


def test_calm_and_missing_direction_have_no_arrow(client, sample, monkeypatch):
    import re
    sample["forecast"]["hourly"]["wind_speed_700hPa"] = [0] * 24
    sample["forecast"]["hourly"]["wind_direction_800hPa"] = [None] * 24
    monkeypatch.setattr(web, "cache", ForecastCache(
        fetcher=lambda s: (sample["forecast"], sample["pressure"])))
    text = client.get("/app").text
    rows = re.findall(r'<tr><th scope="row">(.*?)</tr>', text, re.S)
    assert "Calm" in rows[0] and 'class="wind-arrow"' not in rows[0]
    assert "direction unavailable" in rows[1] and 'class="wind-arrow"' not in rows[1]
    assert 'class="wind-arrow"' not in rows[4]  # Gusts do not acquire an invented direction.


def test_wind_table_is_immediately_before_hourly_evidence(client):
    text = client.get("/app").text
    assert text.index('class="chart-grid"') < text.index('class="card wind-table-card"') < text.index('id="hourly-details"')
    assert 'class="regime-badge' in text


@pytest.mark.parametrize("verdict", ["bad idea", "if you must", "meh", "not bad", "hammer day"])
def test_every_verdict_has_its_own_face(verdict):
    face = web.templates.env.get_template("verdict_face.html").module.face(verdict)
    assert f'data-verdict="{verdict}"' in face
    assert 'aria-hidden="true"' in face
    assert '<svg' in face


def test_unknown_verdict_does_not_invent_a_face():
    assert "<svg" not in web.templates.env.get_template("verdict_face.html").module.face("incomplete data")


def test_cloudbase_secondary_axis_uses_same_inputs_and_units(sample, site):
    report = build_report(site, sample["forecast"], sample["pressure"])
    plot = next(p for p in day_charts(report["hours"][6:21]) if p["title"] == "Temperature − dew point")
    assert plot["secondary"] and plot["secondary_unit"] == "m AGL"
    assert len(plot["lines"]) == 2
    left, right = plot["lines"]
    assert right["secondary"]
    assert right["values"] == [round(max(0, v) * 125, 0) for v in left["values"]]
    for a, b in zip(plot["ticks"], plot["right_ticks"]):
        assert a["y"] == b["y"]
        assert float(b["value"].replace(",", "")) == float(a["value"]) * 125
    assert plot["hover"][0]["readings"][0]["value"].endswith("°C")
    assert plot["hover"][0]["readings"][1]["value"].endswith("m AGL")


def test_cloudbase_missing_and_negative_spread(sample, site):
    hourly = sample["forecast"]["hourly"]
    hourly["temperature_2m"][12] = None
    hourly["temperature_2m"][13] = hourly["dew_point_2m"][13] - 1
    report = build_report(site, sample["forecast"], sample["pressure"])
    plot = next(p for p in day_charts(report["hours"][6:21]) if p["secondary"])
    assert plot["lines"][0]["values"][6] is None
    assert plot["lines"][1]["values"][6] is None
    assert plot["lines"][1]["values"][7] == 0
    assert len(plot["lines"][1]["segments"]) == 2


def test_freezing_axis_uses_readable_metres_not_scientific_notation(sample, site):
    import re
    report = build_report(site, sample["forecast"], sample["pressure"])
    plot = next(p for p in day_charts(report["hours"][6:21]) if p["title"] == "Freezing level")
    assert all(re.fullmatch(r"-?[\d,]+", tick["value"]) for tick in plot["ticks"])
    assert any("," in tick["value"] for tick in plot["ticks"])
    assert plot["left"] >= 80
    assert len(plot["ticks"]) <= 6


def test_regime_labels_preserve_daily_and_hourly_meanings():
    from charts import regime_label
    assert [regime_label(x) for x in ("cap", "capped", "cumulus", "blue", "stable", "off", None)] == [
        "capped", "capped", "cumulus", "blue thermals", "stable", "inactive", "unclassified"]
