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


@pytest.mark.parametrize("values", [(-3.1, -2.7, -1.9), (1.1, 2.7, 3.1), (-8, 0, 2),
                                   (0, 0, 0), (-0.02, 0.01, 0.03), (None, None), ()])
def test_foehn_axis_always_centres_and_marks_zero(values):
    hours = [{"time": f"2026-11-04T{i + 6:02}:00", "complete": False,
              "raw": {"delta_p_foehn": value}} for i, value in enumerate(values)]
    plot = next(p for p in day_charts(hours) if p["title"] == "Foehn pressure gradient")
    ticks = plot["ticks"]
    assert plot["centered_zero"]
    assert ticks[2]["value"] == "0" and ticks[2]["zero"]
    assert ticks[2]["y"] == pytest.approx(90)
    assert float(ticks[0]["value"]) == -float(ticks[-1]["value"])
    assert ticks[0]["y"] == pytest.approx(155)
    assert ticks[-1]["y"] == pytest.approx(25)
    assert all(25 <= p["y"] <= 155 for p in plot["lines"][0]["points"])


@pytest.mark.parametrize("title,levels", [("Wind by level", [925, 850, 800, 700]),
                                         ("Temperature profile", [925, 850, 700]),
                                         ("Relative humidity", [925, 850, 800, 700])])
def test_pressure_level_legends_and_tooltips_include_shared_altitudes(sample, site, title, levels):
    from charts import pressure_label, PRESSURE_ALTITUDES
    report = build_report(site, sample["forecast"], sample["pressure"])
    plot = next(p for p in day_charts(report["hours"][6:21]) if p["title"] == title)
    labels = [line["label"] for line in plot["lines"] if "hPa" in line["label"]]
    assert labels == [pressure_label(level) for level in levels]
    for level, label in zip(levels, labels):
        assert f"≈ {PRESSURE_ALTITUDES[level]:,} m AMSL" in label
        assert all(label in [r["label"] for r in h["readings"]] for h in plot["hover"])
    if title == "Wind by level":
        assert "°" in plot["hover"][0]["readings"][2]["value"]


def test_foehn_zero_reference_is_rendered(client):
    text = client.get("/app").text
    assert text.count('class="grid-line zero-reference"') == 1
    assert 'class="axis-label y-label zero-label"' in text
    assert "0 hPa reference" in text


@pytest.mark.parametrize("code,key", [("off", "inactive"), ("inactive", "inactive"),
    ("cap", "capped"), ("capped", "capped"), ("blue", "blue"), ("cumulus", "cumulus"),
    ("stable", "stable"), ("short", "short"), ("technical", "technical"),
    ("foehn", "foehn"), ("no-data", "unclassified"), (None, "unclassified"),
    ('<script>', "unclassified")])
def test_regime_symbols_have_safe_keys_and_meaning(code, key):
    from regimes import regime_info
    info = regime_info(code)
    assert info["key"] == key
    assert info["label"] and info["description"]


def test_no_window_has_a_distinct_clock_without_changing_the_engine(client, sample, monkeypatch):
    from regimes import regime_info
    assert regime_info("short", False)["key"] == "no-window"
    assert regime_info("short", True)["key"] == "short"
    assert regime_info("foehn", False)["key"] == "foehn"
    sample["forecast"]["hourly"]["wind_gusts_10m"] = [80] * 24
    monkeypatch.setattr(web, "cache", ForecastCache(
        fetcher=lambda s: (sample["forecast"], sample["pressure"])))
    response = client.get("/app")
    assert 'data-regime="no-window"' in response.text
    assert 'data-regime="short"' not in response.text


def test_every_regime_has_an_svg_symbol_and_guide_entry(client):
    from regimes import REGIMES
    from xml.etree import ElementTree as ET
    response = client.get("/static/regimes.svg")
    assert response.status_code == 200
    root = ET.fromstring(response.text)
    symbols = root.findall('{http://www.w3.org/2000/svg}symbol')
    assert {s.attrib["id"] for s in symbols} == set(REGIMES)
    assert len({ET.tostring(s) for s in symbols}) == 10
    guide = client.get("/guide").text
    assert 'id="regime-symbols"' in guide
    assert guide.count('class="regime-key-entry"') == 10
    for label, description in REGIMES.values():
        assert label in guide


def test_icon_controls_expose_names_without_javascript(client):
    text = client.get("/app").text
    assert 'aria-describedby="regime-help"' in text
    assert 'id="regime-help"' in text
    assert 'data-regime-label="' in text and 'data-regime-description="' in text
    assert '/guide#regime-symbols' in text


def test_meduno_coordinates_match_the_published_launch_area():
    site = make_site("Meduno", "icon_eu")
    assert site.latitude == pytest.approx(46 + 13 / 60 + 49.93 / 3600, abs=0.000001)
    assert site.longitude == pytest.approx(12 + 48 / 60 + 23.73 / 3600, abs=0.000001)
    assert site.timezone == "Europe/Rome"
    assert site.launch_dir_center_deg == 225
    assert site.launch_dir_tolerance_deg == 45


def test_meduno_inherited_limits_match_the_disclosure():
    from dataclasses import asdict
    grappa, meduno = (asdict(make_site(name, "icon_eu")) for name in ("Grappa", "Meduno"))
    changed = {"name", "latitude", "longitude", "launch_dir_center_deg", "launch_dir_tolerance_deg", "foehn_north_name", "foehn_south_name"}
    for key in grappa.keys() - changed:
        assert grappa[key] == meduno[key], key
    assert "not calibrated for Meduno" in meduno["foehn_north_name"]


def test_cache_capacity_tracks_all_three_sites_and_models():
    cache = ForecastCache()
    assert len(SITE_PRESETS) == 3
    assert len(cache.locks) == len(SITE_PRESETS) * len(forecast.MODELS) == 15
    assert all(("Meduno", model) in cache.locks for model in forecast.MODELS)


def test_meduno_is_selectable_and_discloses_sources_before_scores(client):
    r = client.get("/app", params={"site": "Meduno", "model": "icon_eu"})
    assert r.status_code == 200
    assert '<option value="Meduno" selected>Meduno · Monte Valinis</option>' in r.text
    assert r.text.index('class="notice site-warning"') < r.text.index('class="day-grid"')
    for text in ("Experimental site preset", "not locally calibrated", "1,100 m", "975 m", "1,088 m",
                 "no dedicated Bora/easterly-flow veto", "FlyCard", "LI-R427", "46.230536", "12.806592",
                 "225° ± 45°", "180°–270°", "Owner-confirmed wind sector"):
        assert text in r.text
    for url in ("https://www.medunoinvolo.it/it/c/869321/il-monte-valinis",
                "https://scuolaparapendioadventure.it/dovevoliamo",
                "https://www.paraglidingmap.com/regions/meduno"):
        assert url in r.text
    assert "3 flying sites" in client.get("/").text
    assert 'class="notice site-warning"' not in client.get("/app?site=Grappa").text


def test_meduno_disclosure_survives_provider_failure(client, monkeypatch):
    def fail(site): raise ForecastError("unreachable")
    monkeypatch.setattr(web, "cache", ForecastCache(fetcher=fail))
    r = client.get("/app?site=Meduno")
    assert r.status_code == 503
    assert "Experimental site preset" in r.text
    assert "Site notes and sources" in r.text


@pytest.mark.parametrize("direction,inside", [(0, False), (90, False), (135, False),
    (179.9, False), (180, True), (225, True), (270, True), (270.1, False),
    (315, False), (360, False)])
def test_meduno_sector_is_applied_by_the_unchanged_engine(sample, direction, inside):
    from core import hard_veto
    site = make_site("Meduno", "icon_eu")
    row = {k: v[12] for k, v in sample["forecast"]["hourly"].items()}
    row["wind_direction_10m"] = direction
    assert ("wind out of sector" not in hard_veto(row, site)[2]) == inside
