"""Public weather retrieval and completeness checks around the unchanged core."""

import math
from datetime import datetime, timedelta, timezone
from threading import Lock
from time import monotonic

import requests

from core import (
    HOURLY_VARS, SITE_PRESETS, SiteConfig, day_summary, enrich_rows_with_wind_deltas,
    evaluate_hour,
)

MODELS = {
    "icon_eu": "DWD ICON Europe",
    "meteofrance_seamless": "Météo-France seamless",
    "ecmwf_ifs": "ECMWF IFS",
    "meteoswiss_icon_ch1": "MeteoSwiss ICON CH1",
    "italia_meteo_arpae_icon_2i": "ItaliaMeteo ICON 2I",
}
API_URL = "https://api.open-meteo.com/v1/forecast"
FORECAST_DAYS = 5
TTL = 1800
# Only variables actually consumed by the scoring functions. Optional diagnostics
# (including unused lightning potential) must not invalidate otherwise complete hours.
REQUIRED = (
    "temperature_2m", "dew_point_2m", "cloud_cover_low", "cloud_cover_mid",
    "cloud_cover_high", "precipitation", "snowfall", "wind_speed_10m",
    "wind_direction_10m", "wind_gusts_10m", "shortwave_radiation", "cape",
    "sunshine_duration", "relative_humidity_925hPa", "relative_humidity_850hPa",
    "relative_humidity_700hPa", "relative_humidity_600hPa", "delta_p_foehn",
    *(f"wind_{kind}_{level}hPa" for level in (925, 850, 800, 700)
      for kind in ("speed", "direction")),
)
TREND_INPUTS = ("wind_speed_10m", "wind_gusts_10m", "wind_speed_925hPa")


class ForecastError(Exception):
    """Stable error code, never an upstream response or credential-bearing URL."""


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def make_site(name, model):
    return SiteConfig(name=name, model=model, **SITE_PRESETS[name])


def read_hourly(payload, variables):
    """Reject malformed time axes; absent or short variables remain unknown."""
    hourly = payload.get("hourly", {})
    times = hourly.get("time", [])
    if not times or len(times) > FORECAST_DAYS * 25:
        raise ForecastError("invalid_data")
    try:
        parsed = [datetime.fromisoformat(t) for t in times]
        if any(t.minute or t.second or t.tzinfo for t in parsed):
            raise ValueError
        if any(b - a != timedelta(hours=1) for a, b in zip(parsed, parsed[1:])):
            raise ValueError
    except (ValueError, TypeError):
        raise ForecastError("invalid_data") from None
    rows = []
    for i, ts in enumerate(times):
        row = {"time": ts}
        for key in variables:
            values = hourly.get(key)
            value = values[i] if isinstance(values, list) and i < len(values) else None
            row[key] = value if number(value) else None
        rows.append(row)
    return rows


def request_json(params):
    try:
        response = requests.get(API_URL, params=params, timeout=(5, 20))
        response.raise_for_status()
        return response.json()
    except requests.HTTPError as exc:
        code = "rate_limited" if exc.response.status_code == 429 else "provider_error"
        raise ForecastError(code) from None
    except (requests.RequestException, ValueError):
        raise ForecastError("unreachable") from None


def fetch_public(site):
    common = {"timezone": site.timezone, "forecast_days": FORECAST_DAYS}
    forecast = request_json({
        **common, "latitude": site.latitude, "longitude": site.longitude,
        "hourly": ",".join(HOURLY_VARS), "models": site.model,
        "wind_speed_unit": "kmh", "temperature_unit": "celsius",
        "precipitation_unit": "mm",
    })
    pressure = request_json({
        **common, "latitude": f"{site.foehn_south_lat},{site.foehn_north_lat}",
        "longitude": f"{site.foehn_south_lon},{site.foehn_north_lon}",
        "hourly": "pressure_msl", "models": "icon_eu",
    })
    if not isinstance(pressure, list) or len(pressure) != 2:
        raise ForecastError("invalid_data")
    south, north = [
        {r["time"]: r["pressure_msl"] for r in read_hourly(p, ["pressure_msl"])}
        for p in pressure
    ]
    # Join timestamps, not array positions: missing pressure cannot shift the series.
    series = {}
    for ts in south.keys() | north.keys():
        s, n = south.get(ts), north.get(ts)
        series[ts] = {
            "pressure_foehn_south": s, "pressure_foehn_north": n,
            "delta_p_foehn": n - s if number(n) and number(s) else None,
        }
    return forecast, series


def build_report(site, payload, pressure):
    rows = read_hourly(payload, HOURLY_VARS)
    for row in rows:
        row.update(pressure.get(row["time"], {}))
    enriched = enrich_rows_with_wind_deltas(rows)
    hours = []
    for i, row in enumerate(enriched):
        missing = [key for key in REQUIRED if not number(row.get(key))]
        if i:
            missing.extend("previous:" + key for key in TREND_INPUTS
                           if not number(rows[i - 1].get(key)))
        else:
            missing.append("previous:hour")
        result = evaluate_hour(row, site) if not missing else {
            "time": row["time"], "veto": False, "fly_score": None,
        }
        result.update(raw=row, missing=missing, complete=not missing)
        hours.append(result)
    days = sorted({h["time"][:10] for h in hours})
    summaries = {}
    for day in days:
        daylight = [h for h in hours if h["time"].startswith(day)
                    and 6 <= int(h["time"][11:13]) <= 20]
        complete = [h for h in daylight if h["complete"]]
        if len(complete) == 15:
            summary = day_summary(complete, day)
        else:
            summary = {"day": day, "verdict": "incomplete data", "best_window": None,
                       "mean_fly_score": None, "tag": "unclassified"}
        summary.update(complete_hours=len(complete), expected_hours=15)
        summaries[day] = summary
    return {"hours": hours, "days": days, "summaries": summaries,
            "fetched_at": datetime.now(timezone.utc),
            **{f"grid_{key}": payload.get(key) if number(payload.get(key)) else None
               for key in ("elevation", "latitude", "longitude")}}


class ForecastCache:
    """Bounded by configured site/model keys; coalesce fetches and back off failures."""

    def __init__(self, fetcher=fetch_public, clock=monotonic):
        self.fetcher = fetcher
        self.clock = clock
        self.entries = {}
        self.locks = {(name, model): Lock() for name in SITE_PRESETS for model in MODELS}

    def get(self, site):
        if site.name not in SITE_PRESETS or site.model not in MODELS:
            raise ForecastError("invalid_selection")
        key = (site.name, site.model)
        with self.locks[key]:
            saved = self.entries.get(key)
            if saved and saved[0] > self.clock():
                if isinstance(saved[1], ForecastError):
                    raise saved[1]
                return saved[1]
            try:
                payload, pressure = self.fetcher(site)
                report = build_report(site, payload, pressure)
            except (ForecastError, KeyError, TypeError, ValueError, AttributeError) as exc:
                error = exc if isinstance(exc, ForecastError) else ForecastError("invalid_data")
                self.entries[key] = (self.clock() + 60, error)
                raise error from None
            self.entries[key] = (self.clock() + TTL, report)
            return report
