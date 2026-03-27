"""
bombometro · core.py
====================
All domain logic: site config, data fetching, enrichment, scoring, verdict.
No UI / no Streamlit dependency — importable from any context.
"""

import json
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

# ──────────────────────────────────────────────────────────────────────────────
# SITE CONFIGURATION
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class SiteConfig:
    name: str
    latitude: float
    longitude: float
    timezone: str
    model: str

    launch_dir_center_deg: float
    launch_dir_tolerance_deg: float

    launch_wind_min_kmh: float
    launch_wind_max_kmh: float
    gust_max_kmh: float
    wind_925_max_kmh: float
    wind_850_max_kmh: float
    wind_800_max_kmh: float
    wind_700_max_kmh: float
    foehn_delta_p_max_hpa: float

    # Foehn reference stations: north = windward (e.g. Innsbruck), south = lee (e.g. Bolzano).
    # delta_p = pressure_north − pressure_south; positive values indicate foehn tendency.
    foehn_north_lat: float
    foehn_north_lon: float
    foehn_south_lat: float
    foehn_south_lon: float

    precip_max_mm: float
    snow_max_cm: float
    cloud_low_max_pct: float

    cloud_cover_low_bad: float
    cloud_cover_mid_bad: float
    shortwave_good: float
    dewpoint_spread_good: float
    cape_max: float

    # Human-readable names for foehn reference stations (display / advisory only).
    foehn_north_name: str = ""
    foehn_south_name: str = ""


_SITES_PATH = Path(__file__).with_name("sites.json")
SITE_PRESETS: Dict[str, Dict[str, Any]] = json.loads(_SITES_PATH.read_text(encoding="utf-8"))

# ──────────────────────────────────────────────────────────────────────────────
# UTILITY HELPERS
# ──────────────────────────────────────────────────────────────────────────────

def safe_value(row: Dict[str, Any], key: str, default: float = 0.0) -> float:
    value = row.get(key)
    return default if value is None else value


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def angle_diff_deg(a: float, b: float) -> float:
    diff = abs(a - b) % 360
    return min(diff, 360 - diff)


_COMPASS_16 = [
    "N", "NNE", "NE", "ENE",
    "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW",
    "W", "WNW", "NW", "NNW",
]

def wind_dir_label(deg: float) -> str:
    """Convert a meteorological wind-from direction (0–360°) to a 16-point compass label.

    Examples: 0→N, 45→NE, 90→E, 180→S, 225→SW, 337.5→NNW.
    """
    idx = round(float(deg) / 22.5) % 16
    return _COMPASS_16[idx]


def linear_score(value: float, good_min: float, good_max: float,
                 hard_min: float, hard_max: float) -> float:
    """0-100 score: 100 inside [good_min, good_max], 0 outside [hard_min, hard_max]."""
    if value < hard_min or value > hard_max:
        return 0.0
    if good_min <= value <= good_max:
        return 100.0
    if value < good_min:
        return 100.0 * (value - hard_min) / (good_min - hard_min)
    return 100.0 * (hard_max - value) / (hard_max - good_max)


def round_or_zero(v: Optional[float], n: int = 1) -> float:
    return round(v, n) if v is not None else 0.0


def round0_or_zero(v: Optional[float]) -> float:
    return round(v, 0) if v is not None else 0.0

# ──────────────────────────────────────────────────────────────────────────────
# OPEN-METEO: HOURLY VARIABLES & FOEHN STATIONS
# ──────────────────────────────────────────────────────────────────────────────

HOURLY_VARS: List[str] = [
    "temperature_2m", "dew_point_2m", "freezing_level_height",
    "cloud_cover_low", "cloud_cover_mid", "cloud_cover_high",
    "precipitation", "snowfall",
    "wind_speed_10m", "wind_direction_10m", "wind_gusts_10m",
    "shortwave_radiation", "cape", "sunshine_duration",
    "wind_speed_925hPa",  "wind_direction_925hPa",
    "relative_humidity_925hPa", "temperature_925hPa",
    "wind_speed_850hPa",  "wind_direction_850hPa",
    "relative_humidity_850hPa", "temperature_850hPa",
    "wind_speed_800hPa",  "wind_direction_800hPa",
    "relative_humidity_800hPa", "temperature_800hPa",
    "wind_speed_700hPa",  "wind_direction_700hPa",
    "relative_humidity_700hPa", "temperature_700hPa",
    "relative_humidity_600hPa", "temperature_600hPa",
    "lightning_potential",
]


# ──────────────────────────────────────────────────────────────────────────────
# FETCH
# ──────────────────────────────────────────────────────────────────────────────

def fetch_forecast(site: SiteConfig, forecast_days: int = 2) -> Dict[str, Any]:
    """Fetch hourly forecast from Open-Meteo for the given site."""
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude":     site.latitude,
        "longitude":    site.longitude,
        "hourly":       ",".join(HOURLY_VARS),
        "timezone":     site.timezone,
        "forecast_days": forecast_days,
        "models":       site.model,
    }
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def fetch_foehn_pressure_series(
    north_lat: float, north_lon: float,
    south_lat: float, south_lon: float,
    timezone: str = "Europe/Rome",
    forecast_days: int = 3,
) -> Dict[str, Dict[str, float]]:
    """
    Fetch hourly MSL pressure for two configurable reference stations.
    north = windward side (e.g. Innsbruck), south = lee side (e.g. Bolzano).
    delta_p_foehn = pressure_north − pressure_south; positive → foehn tendency.
    Returns a dict keyed by ISO timestamp.
    """
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude":      f"{south_lat},{north_lat}",
        "longitude":     f"{south_lon},{north_lon}",
        "hourly":        "pressure_msl",
        "timezone":      timezone,
        "forecast_days": forecast_days,
        "models":        "icon_eu",
    }
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()

    if not isinstance(data, list) or len(data) != 2:
        raise ValueError("Unexpected foehn response format (expected list of 2)")

    south_data, north_data = data[0], data[1]
    series: Dict[str, Dict[str, float]] = {}
    for ts, p_south, p_north in zip(
        south_data["hourly"]["time"],
        south_data["hourly"]["pressure_msl"],
        north_data["hourly"]["pressure_msl"],
    ):
        series[ts] = {
            "pressure_foehn_south": p_south,
            "pressure_foehn_north": p_north,
            # Guard against null values the API occasionally returns at forecast edges
            "delta_p_foehn": (p_north - p_south)
                             if (p_north is not None and p_south is not None)
                             else None,
        }
    return series

# ──────────────────────────────────────────────────────────────────────────────
# DATA RESHAPING & ENRICHMENT
# ──────────────────────────────────────────────────────────────────────────────

def hourly_rows(forecast_json: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Reshape forecast JSON into a flat list of hourly row dicts."""
    hourly = forecast_json["hourly"]
    times  = hourly["time"]
    rows: List[Dict[str, Any]] = []
    for i, ts in enumerate(times):
        row: Dict[str, Any] = {"time": ts}
        for var in HOURLY_VARS:
            vals    = hourly.get(var)
            row[var] = vals[i] if vals is not None else None
        rows.append(row)
    return rows


def enrich_rows_with_foehn_pressure(
    rows: List[Dict[str, Any]],
    pressure_series: Dict[str, Dict[str, float]],
) -> List[Dict[str, Any]]:
    enriched = []
    for row in rows:
        extra = pressure_series.get(row["time"], {
            "pressure_foehn_south": None,
            "pressure_foehn_north": None,
            "delta_p_foehn":        None,
        })
        new_row = row.copy()
        new_row.update(extra)
        enriched.append(new_row)
    return enriched


def enrich_rows_with_wind_deltas(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    enriched = []
    prev = None
    for row in rows:
        new_row = row.copy()
        if prev is None:
            new_row["delta_wind_10m"]    = 0.0
            new_row["delta_gusts_10m"]   = 0.0
            new_row["delta_wind_925hPa"] = 0.0
        else:
            new_row["delta_wind_10m"]    = safe_value(row, "wind_speed_10m")    - safe_value(prev, "wind_speed_10m")
            new_row["delta_gusts_10m"]   = safe_value(row, "wind_gusts_10m")    - safe_value(prev, "wind_gusts_10m")
            new_row["delta_wind_925hPa"] = safe_value(row, "wind_speed_925hPa") - safe_value(prev, "wind_speed_925hPa")
        enriched.append(new_row)
        prev = row
    return enriched

# ──────────────────────────────────────────────────────────────────────────────
# SCORING
# ──────────────────────────────────────────────────────────────────────────────

def hard_veto(row: Dict[str, Any], site: SiteConfig) -> Tuple[bool, Optional[str], List[str]]:
    """Return (vetoed, veto_type, reasons). Vetoed hours are unflayable."""
    reasons:   List[str]      = []
    veto_type: Optional[str]  = None

    wind_dir  = safe_value(row, "wind_direction_10m")
    wind_10m  = safe_value(row, "wind_speed_10m")
    gusts     = safe_value(row, "wind_gusts_10m")
    wind_925  = safe_value(row, "wind_speed_925hPa")
    precip    = safe_value(row, "precipitation")
    snowfall  = safe_value(row, "snowfall", 0.0)
    cloud_low = safe_value(row, "cloud_cover_low")
    delta_p   = safe_value(row, "delta_p_foehn", 0.0)

    dir_diff = angle_diff_deg(wind_dir, site.launch_dir_center_deg)
    if dir_diff > site.launch_dir_tolerance_deg:
        reasons.append("wind out of sector");         veto_type = "wind"
    if round(wind_10m) > site.launch_wind_max_kmh:
        reasons.append("launch wind above limit");    veto_type = veto_type or "wind"
    if round(wind_925) > site.wind_925_max_kmh:
        reasons.append("925 wind above limit");       veto_type = veto_type or "wind"
    if round(gusts) >= site.gust_max_kmh:
        reasons.append("gusts above limit");          veto_type = veto_type or "gusts"
    if precip > site.precip_max_mm:
        reasons.append("rain");                       veto_type = veto_type or "precipitation"
    if snowfall > site.snow_max_cm:
        reasons.append("snow");                       veto_type = veto_type or "precipitation"
    if cloud_low >= site.cloud_low_max_pct:
        reasons.append("low cloud at launch");        veto_type = veto_type or "visibility"
    if delta_p > site.foehn_delta_p_max_hpa * 1.20:
        reasons.append("strong foehn pressure gradient"); veto_type = veto_type or "foehn"

    return (len(reasons) > 0), veto_type, reasons


def launch_score(row: Dict[str, Any], site: SiteConfig) -> Tuple[float, List[str]]:
    reasons    = []
    wind_speed = safe_value(row, "wind_speed_10m")
    gusts      = safe_value(row, "wind_gusts_10m")
    wind_dir   = safe_value(row, "wind_direction_10m")
    cloud_low  = safe_value(row, "cloud_cover_low")

    dir_diff        = angle_diff_deg(wind_dir, site.launch_dir_center_deg)
    direction_score = clamp(100.0 * (1.0 - dir_diff / site.launch_dir_tolerance_deg), 0, 100)

    if wind_speed <= 10.0:
        speed_score = 15.0 + (wind_speed / 10.0) * 85.0
    else:
        speed_score = 100.0 * (1.0 - (wind_speed - 10.0) / max(site.launch_wind_max_kmh - 10.0, 1e-9))
    speed_score = clamp(speed_score, 0, 100)

    gust_ok    = wind_speed + 5.0
    if gusts <= gust_ok:
        gust_score = 100.0
    elif gusts >= site.gust_max_kmh:
        gust_score = 0.0
    else:
        span       = site.gust_max_kmh - gust_ok
        gust_score = 100.0 * (1.0 - (gusts - gust_ok) / span) if span > 0 else 0.0
    gust_score = clamp(gust_score, 0, 100)

    cloud_score = (clamp(100.0 * (1.0 - cloud_low / site.cloud_low_max_pct), 0, 100)
                   if site.cloud_low_max_pct > 0 else 100.0)

    score = clamp(0.30 * direction_score + 0.30 * speed_score
                  + 0.25 * gust_score + 0.15 * cloud_score, 0, 100)

    reasons.append(
        "launch direction well aligned" if dir_diff <= site.launch_dir_tolerance_deg * 0.25 else
        "launch direction acceptable"   if dir_diff <= site.launch_dir_tolerance_deg * 0.60 else
        "launch direction marginal")
    reasons.append(
        "launch wind ideal"  if 8 <= wind_speed <= 12 else
        "launch wind weak"   if wind_speed < 8         else "launch wind strong")
    reasons.append(
        "gusts well behaved" if gusts <= gust_ok else
        "gusts borderline"   if gusts < site.gust_max_kmh else "gusts excessive")
    reasons.append(
        "low cloud clear"     if cloud_low <= site.cloud_low_max_pct * 0.25 else
        "some low cloud"      if cloud_low <= site.cloud_low_max_pct * 0.60 else
        "low cloud intrusive")

    return round(score, 1), reasons


def upper_wind_score(row: Dict[str, Any], site: SiteConfig) -> Tuple[float, List[str]]:
    reasons = []
    w925, w850, w800, w700 = (safe_value(row, k) for k in [
        "wind_speed_925hPa", "wind_speed_850hPa",
        "wind_speed_800hPa", "wind_speed_700hPa"])
    d925, d850, d800, d700 = (safe_value(row, k) for k in [
        "wind_direction_925hPa", "wind_direction_850hPa",
        "wind_direction_800hPa", "wind_direction_700hPa"])

    def peaked(wind: float, peak: float, max_w: float, floor: float = 30.0) -> float:
        if wind <= peak:
            s = floor + (wind / peak) * (100.0 - floor)
        else:
            s = 100.0 * (1.0 - (wind - peak) / max(max_w - peak, 1e-9))
        return clamp(s, 0.0, 100.0)

    s925 = peaked(w925, 15.0, site.wind_925_max_kmh)
    s850 = peaked(w850, 17.0, site.wind_850_max_kmh)
    s800 = peaked(w800, 18.0, site.wind_800_max_kmh)
    op   = 0.40 * s925 + 0.35 * s850 + 0.25 * s800

    aloft_start   = site.wind_700_max_kmh * 0.5
    aloft_penalty = (0.0          if w700 <= aloft_start else
                     30.0         if w700 >= site.wind_700_max_kmh else
                     30.0 * (w700 - aloft_start) / (site.wind_700_max_kmh - aloft_start))

    speed_jumps = [abs(w850 - w925), abs(w800 - w850), abs(w700 - w800)]
    dir_jumps   = [angle_diff_deg(d850, d925), angle_diff_deg(d800, d850), angle_diff_deg(d700, d800)]

    def spj(j: float) -> float: return 0.0 if j <= 8  else 1.0 if j >= 20 else (j - 8)  / 12
    def dj(j:  float) -> float: return 0.0 if j <= 20 else 1.0 if j >= 60 else (j - 20) / 40

    coh_pen = 35.0 * (0.6 * sum(spj(j) for j in speed_jumps) / 3
                    + 0.4 * sum(dj(j)  for j in dir_jumps)   / 3)
    score   = clamp(op - aloft_penalty - coh_pen, 0.0, 100.0)

    def lr(lbl: str, w: float, peak: float, mx: float) -> str:
        return (f"{lbl} wind weak"       if w <= peak * 0.60  else
                f"{lbl} wind favorable"  if w <= peak * 1.15  else
                f"{lbl} wind strong"     if w < mx            else
                f"{lbl} wind near limit")

    for lbl, w, peak, mx in [
        ("925", w925, 15.0, site.wind_925_max_kmh),
        ("850", w850, 17.0, site.wind_850_max_kmh),
        ("800", w800, 18.0, site.wind_800_max_kmh),
    ]:
        reasons.append(lr(lbl, w, peak, mx))

    reasons.append(
        "high-altitude wind moderate"   if w700 <= aloft_start           else
        "high-altitude wind strong"     if w700 < site.wind_700_max_kmh  else
        "high-altitude wind very strong")
    reasons.append(
        "vertical profile coherent" if coh_pen < 10 else
        "some vertical shear"       if coh_pen < 22 else "strong vertical shear")

    return round(score, 1), reasons


def foehn_score(row: Dict[str, Any], site: SiteConfig) -> Tuple[float, List[str]]:
    reasons = []
    delta_p = safe_value(row, "delta_p_foehn", 0.0)

    w925, w850, w800, w700 = (safe_value(row, k) for k in [
        "wind_speed_925hPa", "wind_speed_850hPa",
        "wind_speed_800hPa", "wind_speed_700hPa"])
    d925, d850, d800, d700 = (safe_value(row, k) for k in [
        "wind_direction_925hPa", "wind_direction_850hPa",
        "wind_direction_800hPa", "wind_direction_700hPa"])

    p_sc = (0.0   if delta_p <= 0 else
            100.0 if delta_p >= site.foehn_delta_p_max_hpa else
            100.0 * delta_p / site.foehn_delta_p_max_hpa)

    def north_sc(d: float, tol: float = 70.0) -> float:
        diff = angle_diff_deg(d, 0.0)
        return 0.0 if diff >= tol else 100.0 * (1.0 - diff / tol)

    def wsup(w: float, mx: float) -> float:
        return clamp(100.0 * w / mx, 0.0, 100.0) if mx > 0 else 0.0

    lvls   = [(w925, d925, site.wind_925_max_kmh), (w850, d850, site.wind_850_max_kmh),
              (w800, d800, site.wind_800_max_kmh), (w700, d700, site.wind_700_max_kmh)]
    scores = [0.7 * north_sc(d) + 0.3 * wsup(w, mx) for w, d, mx in lvls]
    n_sc   = 0.35 * scores[0] + 0.25 * scores[1] + 0.20 * scores[2] + 0.20 * scores[3]

    deltas = [w850 - w925, w800 - w850, w700 - w800]
    def gstep(dw: float) -> float:
        return 20.0 + min(dw, 20.0) / 20.0 * 80.0 if dw > 0 else 20.0
    vp_sc = sum(gstep(d) for d in deltas) / 3.0

    score = clamp(0.50 * p_sc + 0.35 * n_sc + 0.15 * vp_sc, 0.0, 100.0)

    reasons.append(
        "weak north-south pressure gradient"     if p_sc < 20 else
        "moderate north-south pressure gradient" if p_sc < 60 else
        "strong north-south pressure gradient")
    for lbl, d in [("700", north_sc(d700)), ("850", north_sc(d850)), ("925", north_sc(d925))]:
        reasons.append(
            f"{lbl} flow strongly northerly"      if d >= 75 else
            f"{lbl} flow partly northerly"        if d >= 40 else
            f"{lbl} flow not clearly northerly")
    reasons.append(
        "wind increases with height"                  if vp_sc >= 70 else
        "vertical wind profile partly supportive"     if vp_sc >= 40 else
        "vertical wind profile weakly supportive")

    return round(score, 1), reasons


def thermal_score(row: Dict[str, Any]) -> Dict[str, Any]:
    """
    Returns a dict with keys:
      thermal_score, thermal_reasons, thermal_active,
      cloudbase_estimate_m, cloudbase_band, thermal_regime
    """
    reasons = []
    hour     = int(row["time"][11:13])
    temp_2m  = safe_value(row, "temperature_2m")
    dew_2m   = safe_value(row, "dew_point_2m")
    shortwave= safe_value(row, "shortwave_radiation")
    sunshine = safe_value(row, "sunshine_duration")
    cape     = safe_value(row, "cape")
    cloud_low= safe_value(row, "cloud_cover_low")
    cloud_mid= safe_value(row, "cloud_cover_mid")
    cloud_hi = safe_value(row, "cloud_cover_high", 0.0)
    rh_925   = safe_value(row, "relative_humidity_925hPa", 50.0)
    rh_850   = safe_value(row, "relative_humidity_850hPa", 50.0)

    sw_sc   = (0.0 if shortwave <= 100 else
               100.0 if shortwave >= 700 else 100.0 * (shortwave - 100.0) / 600.0)
    sun_sc  = (0.0 if sunshine  <= 0   else
               100.0 if sunshine >= 2700 else 100.0 * sunshine / 2700.0)
    cl_sc   = (0.40 * clamp(100.0 * (1.0 - cloud_low / 100.0), 0, 100) +
               0.45 * clamp(100.0 * (1.0 - cloud_mid / 100.0), 0, 100) +
               0.15 * clamp(100.0 * (1.0 - cloud_hi  / 100.0), 0, 100))
    heat_sc = clamp(0.45 * sw_sc + 0.25 * sun_sc + 0.30 * cl_sc, 0, 100)

    spread    = temp_2m - dew_2m
    spread_sc = (0.0 if spread <= 0 else 100.0 if spread >= 12 else 100.0 * spread / 12.0)
    cape_sc   = (0.0 if cape   <= 0 else 100.0 if cape   >= 600 else 100.0 * cape   / 600.0)
    resp_sc   = clamp(0.75 * spread_sc + 0.25 * cape_sc, 0, 100)

    t_sc          = clamp(0.70 * heat_sc + 0.30 * resp_sc, 0, 100)
    cloudbase_m   = 0.0 if spread <= 0 else 125.0 * spread
    cb_band       = ("low" if cloudbase_m < 800 else "medium" if cloudbase_m < 1800 else "high")

    mean_rh = (rh_925 + rh_850) / 2.0
    if hour < 9 or hour > 19 or t_sc < 35 or shortwave < 120 or sunshine < 600:
        regime = "off"
    elif cloud_mid >= 85:
        regime = "cap"
    elif t_sc >= 55:
        if   spread >= 9 and cloud_low <= 20 and mean_rh <= 45:
            regime = "blue"
        elif 5 <= spread <= 10 and mean_rh >= 45 and cloud_low <= 50:
            regime = "cumulus"
        else:
            regime = "blue" if spread > 8 else "cumulus"
    else:
        regime = "cap" if cloud_mid >= 70 else "off"

    active = (9 <= hour <= 19 and t_sc >= 55 and shortwave >= 180
              and sunshine >= 900 and cloud_mid < 85
              and safe_value(row, "precipitation") <= 0.0)

    reasons.append(
        "strong solar input"   if shortwave >= 500 else
        "moderate solar input" if shortwave >= 250 else "weak solar input")
    reasons.append(
        "good sunshine duration" if sunshine >= 2400 else
        "partial sunshine"       if sunshine >= 1200 else "limited sunshine")
    if cloud_mid >= 85:  reasons.append("too much mid cloud")
    elif cloud_low >= 60: reasons.append("substantial low cloud")
    reasons.append(
        "dry boundary layer"                       if spread >= 10 else
        "moderate temperature-dewpoint spread"     if spread >= 6  else
        "humid boundary layer")
    if cape >= 300: reasons.append("convective support present")
    reasons.append({
        "blue":   "blue thermals likely",
        "cumulus":"cumulus likely",
        "cap":    "clouds likely capping development",
    }.get(regime, "little thermal activity expected"))

    return {
        "thermal_score":        round(t_sc, 1),
        "thermal_reasons":      reasons,
        "thermal_active":       active,
        "cloudbase_estimate_m": round(cloudbase_m, 0),
        "cloudbase_band":       cb_band,
        "thermal_regime":       regime,
    }


def risk_score(row: Dict[str, Any], site: SiteConfig) -> Tuple[float, List[str]]:
    reasons  = []
    cape     = safe_value(row, "cape")
    precip   = safe_value(row, "precipitation")
    cloud_mid= safe_value(row, "cloud_cover_mid")
    cloud_hi = safe_value(row, "cloud_cover_high", 0.0)
    rh700    = safe_value(row, "relative_humidity_700hPa", 50.0)
    rh600    = safe_value(row, "relative_humidity_600hPa", 50.0)
    dw10     = max(safe_value(row, "delta_wind_10m"),    0.0)
    dg10     = max(safe_value(row, "delta_gusts_10m"),   0.0)
    dw925    = max(safe_value(row, "delta_wind_925hPa"), 0.0)

    cape_risk  = clamp(100.0 * cape / 800.0, 0, 100) if cape > 0 else 0.0
    cloud_risk = clamp(0.65 * cloud_mid + 0.35 * cloud_hi, 0, 100)
    hum_risk   = clamp((rh700 + rh600) / 2.0, 0, 100)
    prec_risk  = clamp(100.0 * precip, 0, 100) if precip > 0 else 0.0
    storm_risk = clamp(0.35 * cape_risk + 0.25 * cloud_risk
                     + 0.20 * hum_risk  + 0.20 * prec_risk, 0, 100)

    def jsc(d: float, s: float, f: float) -> float:
        return 0.0 if d <= s else 100.0 if d >= f else 100.0 * (d - s) / (f - s)

    wjr   = clamp(0.20 * jsc(dw10, 3, 10) + 0.35 * jsc(dg10, 4, 12)
                + 0.45 * jsc(dw925, 3, 10), 0, 100)
    score = clamp(0.60 * storm_risk + 0.40 * wjr, 0, 100)

    if storm_risk >= 65: reasons.append("risk of overdevelopment")
    elif storm_risk >= 35: reasons.append("some convective instability")
    if precip > 0:          reasons.append("precipitation signal present")
    elif cloud_mid >= 75:   reasons.append("strong mid-cloud build-up")
    if hum_risk >= 75:      reasons.append("humid upper levels")
    if wjr >= 65:           reasons.append("wind increasing rapidly")
    elif wjr >= 35:         reasons.append("wind strengthening")
    if dw925 >= 5:          reasons.append("launch-level wind rising")
    elif dg10 >= 5:         reasons.append("gusts rising")

    return round(score, 1), reasons

# ──────────────────────────────────────────────────────────────────────────────
# HOUR-BY-HOUR EVALUATION
# ──────────────────────────────────────────────────────────────────────────────

def evaluate_hour(row: Dict[str, Any], site: SiteConfig) -> Dict[str, Any]:
    veto, veto_type, veto_reasons = hard_veto(row, site)
    f_sc, f_reasons               = foehn_score(row, site)

    # Always compute all component scores so that:
    # - potential_score is available even for vetoed hours (shadow line in UI)
    # - cloudbase_estimate_m is available even when flying is vetoed
    l_sc,  l_reasons = launch_score(row, site)
    u_sc,  u_reasons = upper_wind_score(row, site)
    th               = thermal_score(row)
    r_sc,  r_reasons = risk_score(row, site)

    potential  = clamp(0.25 * l_sc + 0.35 * u_sc + 0.40 * th["thermal_score"], 0, 100)
    risk_pen   = 20.0 * r_sc / 100.0

    # ── thermal–foehn interaction ─────────────────────────────────────────────
    # Strong thermals partially attenuate foehn influence at pilot level:
    # convective mixing disrupts low-level foehn turbulence and pilots can climb
    # above rotor zones quickly. The interaction is largest when thermals are
    # good AND foehn is moderate; it vanishes at both extremes (zero thermal, or
    # extreme foehn that no amount of lift can compensate for).
    # Only affects scoring — the hard veto (pressure gradient) is never touched.
    _FOEHN_THERMAL_MAX_ATT = 25.0   # max attenuation in score points
    _thermal_f = clamp(th["thermal_score"] / 100.0, 0.0, 1.0)
    _foehn_f   = clamp(f_sc / 100.0,                0.0, 1.0)
    _att       = _FOEHN_THERMAL_MAX_ATT * _thermal_f * (1.0 - _foehn_f)
    f_sc_adj   = clamp(f_sc - _att, 0.0, 100.0)

    foehn_pen  = (0.0  if f_sc_adj <= 40  else
                  25.0 if f_sc_adj >= 100 else
                  25.0 * (f_sc_adj - 40.0) / 60.0)
    fly_sc     = clamp(potential - risk_pen - foehn_pen, 0, 100)

    return {
        "time": row["time"], "veto": veto, "veto_type": veto_type,
        "veto_reasons": veto_reasons,
        # Component scores are always populated so bars render even on vetoed hours
        # (vetoed hours show ghost bars, useful to understand *why* the potential
        # existed despite the veto).  fly_score is None only when vetoed.
        "launch_score":      round(l_sc, 1),
        "launch_reasons":    l_reasons,
        "upper_wind_score":  round(u_sc, 1),
        "upper_wind_reasons": u_reasons,
        "thermal_score":     round(th["thermal_score"], 1),
        "thermal_reasons":   th["thermal_reasons"],
        "thermal_active":    th["thermal_active"],
        "cloudbase_estimate_m": th["cloudbase_estimate_m"],
        "cloudbase_band":    th["cloudbase_band"],
        "thermal_regime":    th["thermal_regime"],
        "risk_score":        round(r_sc, 1),
        "risk_reasons":      r_reasons,
        "foehn_score":       round(f_sc, 1),       # raw, used in chart
        "foehn_score_adj":   round(f_sc_adj, 1),   # after thermal attenuation, used in scoring
        "foehn_attenuation": round(_att, 1),        # diagnostic: how many points were shaved off
        "foehn_reasons":     f_reasons,
        "potential_score":   round(potential, 1),   # always populated
        "risk_penalty":      round(risk_pen,  1) if not veto else None,
        "foehn_penalty":     round(foehn_pen, 1) if not veto else None,
        "fly_score":         round(fly_sc,    1) if not veto else None,
    }

# ──────────────────────────────────────────────────────────────────────────────
# DAY-LEVEL VERDICT
# ──────────────────────────────────────────────────────────────────────────────

def day_summary(evaluated_hours: List[Dict[str, Any]], day: str) -> Dict[str, Any]:
    """
    Summarise one calendar day.
    Verdict labels: bad idea / if you must / meh / not bad / hammer day
    """
    day_rows = [r for r in evaluated_hours if r["time"].startswith(day)]

    def safe_mean(vals: List[Optional[float]]) -> Optional[float]:
        v = [x for x in vals if x is not None]
        return sum(v) / len(v) if v else None

    def most_common_nn(vals: List[Any]) -> Any:
        v = [x for x in vals if x is not None]
        return Counter(v).most_common(1)[0][0] if v else None

    def downgrade(v: str) -> str:
        order = ["bad idea", "if you must", "meh", "not bad", "hammer day"]
        return order[max(0, order.index(v) - 1)]

    # ── no data ──────────────────────────────────────────────────────────────
    if not day_rows:
        return {"day": day, "verdict": "bad idea", "tag": "no-data",
                "best_window": None, "best_window_duration_h": 0,
                "mean_fly_score": 0.0, "mean_potential_score": 0.0,
                "mean_foehn_score": 0.0, "mean_risk_score": 0.0,
                "thermal_hours_in_window": 0, "typical_cloudbase_m": 0.0,
                "dominant_thermal_regime": "off", "usable_hours": 0,
                "usable_windows_found": 0, "reasons": ["no data"]}

    # ── build usable hours (not vetoed, fly_score >= 35) ─────────────────────
    usable = [r for r in day_rows
              if not r["veto"] and r["fly_score"] is not None and r["fly_score"] >= 35]

    if not usable:
        nv   = [r for r in day_rows if not r["veto"]]
        mf   = safe_mean([r["foehn_score"] for r in nv]) if nv else None
        mr   = safe_mean([r["risk_score"]  for r in nv]) if nv else None
        tag  = ("foehn"     if mf and mf > 75 else
                "technical" if mr and mr > 60 else
                "capped"    if most_common_nn([r.get("thermal_regime") for r in nv]) == "cap" else
                "short")
        return {"day": day, "verdict": "bad idea", "tag": tag,
                "best_window": None, "best_window_duration_h": 0,
                "mean_fly_score": 0.0,
                "mean_potential_score": round_or_zero(safe_mean([r["potential_score"] for r in nv])),
                "mean_foehn_score": round_or_zero(mf), "mean_risk_score": round_or_zero(mr),
                "thermal_hours_in_window": 0, "typical_cloudbase_m": 0.0,
                "dominant_thermal_regime": "off", "usable_hours": 0,
                "usable_windows_found": 0, "reasons": ["no usable hours"]}

    # ── build contiguous windows ──────────────────────────────────────────────
    usable_times = {r["time"] for r in usable}
    windows: List[List[Dict[str, Any]]] = []
    cur:     List[Dict[str, Any]]       = []
    for r in day_rows:
        if r["time"] in usable_times:
            cur.append(r)
        else:
            if cur: windows.append(cur); cur = []
    if cur: windows.append(cur)

    real = [w for w in windows if len(w) >= 2]

    if not real:
        best1 = max(usable, key=lambda x: x["fly_score"])
        return {"day": day, "verdict": "if you must", "tag": "short",
                "best_window": (best1["time"][-5:], best1["time"][-5:]),
                "best_window_duration_h": 1,
                "mean_fly_score":       round_or_zero(best1["fly_score"]),
                "mean_potential_score": round_or_zero(best1["potential_score"]),
                "mean_foehn_score":     round_or_zero(best1["foehn_score"]),
                "mean_risk_score":      round_or_zero(best1["risk_score"]),
                "thermal_hours_in_window": 1 if best1.get("thermal_active") else 0,
                "typical_cloudbase_m":  round0_or_zero(best1.get("cloudbase_estimate_m")),
                "dominant_thermal_regime": best1.get("thermal_regime") or "off",
                "usable_hours": len(usable), "usable_windows_found": 0,
                "reasons": ["only isolated usable hour found"]}

    # ── score each window ─────────────────────────────────────────────────────
    wsums = []
    for w in real:
        dur  = len(w)
        mf   = safe_mean([r["fly_score"]       for r in w])
        mp   = safe_mean([r["potential_score"]  for r in w])
        mfn  = safe_mean([r["foehn_score"]      for r in w])
        mr   = safe_mean([r["risk_score"]       for r in w])
        val  = 0.60 * (mf or 0) + 0.20 * min(dur / 5.0, 1.0) * 100.0 + 0.20 * (mp or 0)
        wsums.append({
            "start": w[0]["time"][-5:], "end": w[-1]["time"][-5:], "duration": dur,
            "mean_fly": mf, "mean_potential": mp, "mean_foehn": mfn, "mean_risk": mr,
            "thermal_hours": sum(1 for r in w if r.get("thermal_active")),
            "mean_cloudbase": safe_mean([r.get("cloudbase_estimate_m") for r in w]),
            "dominant_regime": most_common_nn([r.get("thermal_regime") for r in w]),
            "window_value": val,
        })

    best = max(wsums, key=lambda x: x["window_value"])
    mf, mp = best["mean_fly"], best["mean_potential"]
    mfn, mr, dur = best["mean_foehn"] or 0.0, best["mean_risk"] or 0.0, best["duration"]

    # ── verdict ───────────────────────────────────────────────────────────────
    verdict = ("if you must" if mf < 45 else
               "meh"         if mf < 58 else
               "not bad"     if mf < 72 else
               "hammer day"  if dur >= 4 and mp is not None and mp >= 70 else "not bad")

    if mfn > 90:                                             verdict = downgrade(verdict)
    elif mfn > 80 and verdict in ["not bad", "hammer day"]: verdict = downgrade(verdict)
    if mr  > 75 and verdict in ["meh", "not bad", "hammer day"]: verdict = downgrade(verdict)

    # ── tag ───────────────────────────────────────────────────────────────────
    dr  = best["dominant_regime"]
    tag = ("short" if dur <= 2 else "stable")
    tag = {"blue": "blue", "cumulus": "cumulus", "cap": "capped"}.get(dr, tag)
    if mr  > 60: tag = "technical"
    if mfn > 75: tag = "foehn"

    # ── reasons ───────────────────────────────────────────────────────────────
    reasons = [
        f"best window {best['start']}–{best['end']}",
        f"mean fly score {mf:.1f}" if mf else "",
        f"window duration {dur} h",
    ]
    if best["thermal_hours"] > 0:
        reasons.append(f"{best['thermal_hours']} thermal-active hours in best window")
    if mfn > 90: reasons.append("very strong foehn signal degraded the day")
    if mr  > 75: reasons.append("risk/technicality degraded the day")
    reasons = [r for r in reasons if r]

    return {
        "day": day, "verdict": verdict, "tag": tag,
        "best_window": (best["start"], best["end"]),
        "best_window_duration_h": dur,
        "mean_fly_score":         round_or_zero(mf),
        "mean_potential_score":   round_or_zero(mp),
        "mean_foehn_score":       round_or_zero(mfn),
        "mean_risk_score":        round_or_zero(mr),
        "thermal_hours_in_window": best["thermal_hours"],
        "typical_cloudbase_m":    round0_or_zero(best["mean_cloudbase"]),
        "dominant_thermal_regime": dr or "off",
        "usable_hours":           len(usable),
        "usable_windows_found":   len(real),
        "reasons":                reasons,
    }

# ──────────────────────────────────────────────────────────────────────────────
# SUN TIMES  (astral — pure astronomical calculation, no API)
# ──────────────────────────────────────────────────────────────────────────────

def get_sun_times(lat: float, lon: float, timezone: str, day: str) -> Dict[str, Any]:
    """
    Return sunrise, solar noon, and sunset for the given location and date.
    All values are timezone-aware datetime objects in the site's local timezone.
    Requires: astral
    """
    import datetime
    from zoneinfo import ZoneInfo
    from astral import LocationInfo
    from astral.sun import sun as astral_sun

    tz       = ZoneInfo(timezone)
    d        = datetime.date.fromisoformat(day)
    observer = LocationInfo(latitude=lat, longitude=lon).observer
    s        = astral_sun(observer, date=d, tzinfo=tz)
    return {
        "sunrise":    s["sunrise"],
        "solar_noon": s["noon"],
        "sunset":     s["sunset"],
    }


# ──────────────────────────────────────────────────────────────────────────────
# PIPELINE HELPER  (fetch → enrich → evaluate → summarise)
# ──────────────────────────────────────────────────────────────────────────────

def run_pipeline(
    site: SiteConfig,
    forecast_days: int,
    forecast_json: Dict[str, Any],
    pressure_series: Dict[str, Dict[str, float]],
) -> Dict[str, Any]:
    """
    Given pre-fetched JSON blobs, run the full enrichment + scoring pipeline.

    Returns:
        {
          "rows":           List[Dict],   # enriched hourly rows
          "evaluated":      List[Dict],   # hour-by-hour evaluation
          "available_days": List[str],    # sorted YYYY-MM-DD strings
          "summaries":      Dict[str, Dict],  # day -> day_summary
        }
    """
    rows = hourly_rows(forecast_json)
    rows = enrich_rows_with_foehn_pressure(rows, pressure_series)
    rows = enrich_rows_with_wind_deltas(rows)

    evaluated     = [evaluate_hour(r, site) for r in rows]
    available_days = sorted({r["time"][:10] for r in evaluated})
    summaries      = {d: day_summary(evaluated, d) for d in available_days}

    return {
        "rows":           rows,
        "evaluated":      evaluated,
        "available_days": available_days,
        "summaries":      summaries,
    }
