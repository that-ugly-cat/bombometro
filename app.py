"""
bombometro – Streamlit Cloud app
Paragliding day classifier powered by Open-Meteo.
"""

import math
from collections import Counter
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
import requests
import streamlit as st
from matplotlib.gridspec import GridSpec

# ──────────────────────────────────────────────────────────────────────────────
# PAGE CONFIG
# ──────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="💣 Bombometro",
    page_icon="🪂",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ──────────────────────────────────────────────────────────────────────────────
# SITE CONFIG
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
    precip_max_mm: float
    snow_max_cm: float
    cloud_low_max_pct: float
    cloud_cover_low_bad: float
    cloud_cover_mid_bad: float
    shortwave_good: float
    dewpoint_spread_good: float
    cape_max: float


SITE_PRESETS = {
    "Montegrappa": dict(
        latitude=45.810, longitude=11.773, timezone="Europe/Rome",
        launch_dir_center_deg=180.0, launch_dir_tolerance_deg=90.0,
        launch_wind_min_kmh=0.0, launch_wind_max_kmh=25.0,
        gust_max_kmh=30.0, wind_925_max_kmh=30.0, wind_850_max_kmh=35.0,
        wind_800_max_kmh=38.0, wind_700_max_kmh=60.0, foehn_delta_p_max_hpa=8.0,
        precip_max_mm=0.1, snow_max_cm=0.1, cloud_low_max_pct=98.0,
        cloud_cover_low_bad=85.0, cloud_cover_mid_bad=85.0,
        shortwave_good=500.0, dewpoint_spread_good=8.0, cape_max=1800.0,
    ),
    "Custom": dict(
        latitude=45.0, longitude=11.0, timezone="Europe/Rome",
        launch_dir_center_deg=180.0, launch_dir_tolerance_deg=90.0,
        launch_wind_min_kmh=0.0, launch_wind_max_kmh=25.0,
        gust_max_kmh=30.0, wind_925_max_kmh=30.0, wind_850_max_kmh=35.0,
        wind_800_max_kmh=38.0, wind_700_max_kmh=60.0, foehn_delta_p_max_hpa=8.0,
        precip_max_mm=0.1, snow_max_cm=0.1, cloud_low_max_pct=98.0,
        cloud_cover_low_bad=85.0, cloud_cover_mid_bad=85.0,
        shortwave_good=500.0, dewpoint_spread_good=8.0, cape_max=1800.0,
    ),
}

# ──────────────────────────────────────────────────────────────────────────────
# SIDEBAR
# ──────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("🪂 Bombometro")
    st.caption("Paragliding day classifier · Open-Meteo")
    st.divider()

    preset = st.selectbox("Site preset", list(SITE_PRESETS.keys()))
    p = SITE_PRESETS[preset]

    with st.expander("📍 Location", expanded=(preset == "Custom")):
        site_name = st.text_input("Site name", value=preset)
        lat  = st.number_input("Latitude",  value=p["latitude"],  format="%.4f")
        lon  = st.number_input("Longitude", value=p["longitude"], format="%.4f")
        tz   = st.text_input("Timezone", value=p["timezone"])
        model = st.selectbox("Model", ["icon_eu", "ecmwf_ifs025", "gfs_seamless", "meteofrance_seamless"], index=0)

    with st.expander("🧭 Launch window"):
        dir_center = st.number_input("Dir center (°)", value=p["launch_dir_center_deg"], step=5.0)
        dir_tol    = st.number_input("Dir tolerance (°)", value=p["launch_dir_tolerance_deg"], step=5.0)
        wind_min   = st.number_input("Wind min (km/h)", value=p["launch_wind_min_kmh"], step=1.0)
        wind_max   = st.number_input("Wind max (km/h)", value=p["launch_wind_max_kmh"], step=1.0)
        gust_max   = st.number_input("Gusts max (km/h)", value=p["gust_max_kmh"], step=1.0)

    with st.expander("🌬️ Upper winds"):
        w925_max = st.number_input("925 hPa max (km/h)", value=p["wind_925_max_kmh"], step=1.0)
        w850_max = st.number_input("850 hPa max (km/h)", value=p["wind_850_max_kmh"], step=1.0)
        w800_max = st.number_input("800 hPa max (km/h)", value=p["wind_800_max_kmh"], step=1.0)
        w700_max = st.number_input("700 hPa max (km/h)", value=p["wind_700_max_kmh"], step=1.0)

    with st.expander("🌧️ Precip & clouds"):
        precip_max   = st.number_input("Precip max (mm/h)", value=p["precip_max_mm"], step=0.05, format="%.2f")
        snow_max     = st.number_input("Snow max (cm)",    value=p["snow_max_cm"],   step=0.05, format="%.2f")
        cloud_lo_max = st.number_input("Low cloud max (%)", value=p["cloud_low_max_pct"], step=1.0)

    with st.expander("🌡️ Foehn"):
        foehn_dp = st.number_input("Foehn ΔP max (hPa)", value=p["foehn_delta_p_max_hpa"], step=0.5)

    forecast_days = st.slider("Forecast days", 1, 7, 2)
    fetch_btn = st.button("🔄 Fetch forecast", type="primary", use_container_width=True)

SITE = SiteConfig(
    name=site_name, latitude=lat, longitude=lon, timezone=tz, model=model,
    launch_dir_center_deg=dir_center, launch_dir_tolerance_deg=dir_tol,
    launch_wind_min_kmh=wind_min, launch_wind_max_kmh=wind_max,
    gust_max_kmh=gust_max, wind_925_max_kmh=w925_max,
    wind_850_max_kmh=w850_max, wind_800_max_kmh=w800_max,
    wind_700_max_kmh=w700_max, foehn_delta_p_max_hpa=foehn_dp,
    precip_max_mm=precip_max, snow_max_cm=snow_max, cloud_low_max_pct=cloud_lo_max,
    cloud_cover_low_bad=p["cloud_cover_low_bad"], cloud_cover_mid_bad=p["cloud_cover_mid_bad"],
    shortwave_good=p["shortwave_good"], dewpoint_spread_good=p["dewpoint_spread_good"],
    cape_max=p["cape_max"],
)

# ──────────────────────────────────────────────────────────────────────────────
# PURE LOGIC (copied from notebook)
# ──────────────────────────────────────────────────────────────────────────────
def safe_value(row: Dict[str, Any], key: str, default: float = 0.0) -> float:
    value = row.get(key)
    return default if value is None else value

def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))

def angle_diff_deg(a: float, b: float) -> float:
    diff = abs(a - b) % 360
    return min(diff, 360 - diff)

def linear_score(value, good_min, good_max, hard_min, hard_max):
    if value < hard_min or value > hard_max:
        return 0.0
    if good_min <= value <= good_max:
        return 100.0
    if value < good_min:
        return 100.0 * (value - hard_min) / (good_min - hard_min)
    return 100.0 * (hard_max - value) / (hard_max - good_max)


HOURLY_VARS = [
    "temperature_2m", "dew_point_2m", "freezing_level_height",
    "cloud_cover_low", "cloud_cover_mid", "cloud_cover_high",
    "precipitation", "wind_speed_10m", "wind_direction_10m", "wind_gusts_10m",
    "shortwave_radiation", "cape", "sunshine_duration",
    "wind_speed_925hPa", "wind_direction_925hPa",
    "relative_humidity_925hPa", "temperature_925hPa",
    "wind_speed_850hPa", "wind_direction_850hPa",
    "relative_humidity_850hPa", "temperature_850hPa",
    "wind_speed_800hPa", "wind_direction_800hPa",
    "relative_humidity_800hPa", "temperature_800hPa",
    "wind_speed_700hPa", "wind_direction_700hPa",
    "relative_humidity_700hPa", "temperature_700hPa",
    "relative_humidity_600hPa", "temperature_600hPa",
    "lightning_potential",
]

BOLZANO   = {"latitude": 46.4983, "longitude": 11.3548}
INNSBRUCK = {"latitude": 47.2692, "longitude": 11.4041}


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_forecast(lat, lon, tz, model, forecast_days):
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat, "longitude": lon,
        "hourly": ",".join(HOURLY_VARS),
        "timezone": tz,
        "forecast_days": forecast_days,
        "models": model,
    }
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_foehn_pressure_series(tz, forecast_days):
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude":  f"{BOLZANO['latitude']},{INNSBRUCK['latitude']}",
        "longitude": f"{BOLZANO['longitude']},{INNSBRUCK['longitude']}",
        "hourly": "pressure_msl",
        "timezone": tz,
        "forecast_days": forecast_days,
        "models": "icon_eu",
    }
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, list) or len(data) != 2:
        raise ValueError("Unexpected foehn response format")
    bz, inn = data[0], data[1]
    series = {}
    for ts, p_bz, p_inn in zip(bz["hourly"]["time"], bz["hourly"]["pressure_msl"],
                                inn["hourly"]["pressure_msl"]):
        series[ts] = {
            "pressure_bolzano": p_bz,
            "pressure_innsbruck": p_inn,
            "delta_p_innsbruck_bolzano": p_inn - p_bz,
        }
    return series


def hourly_rows(forecast_json):
    hourly = forecast_json["hourly"]
    times = hourly["time"]
    rows = []
    for i, ts in enumerate(times):
        row = {"time": ts}
        for var in HOURLY_VARS:
            vals = hourly.get(var)
            row[var] = vals[i] if vals is not None else None
        rows.append(row)
    return rows


def enrich_rows_with_foehn_pressure(rows, pressure_series):
    enriched = []
    for row in rows:
        ts = row["time"]
        extra = pressure_series.get(ts, {
            "pressure_bolzano": None,
            "pressure_innsbruck": None,
            "delta_p_innsbruck_bolzano": None,
        })
        new_row = row.copy()
        new_row.update(extra)
        enriched.append(new_row)
    return enriched


def enrich_rows_with_wind_deltas(rows):
    enriched = []
    prev = None
    for row in rows:
        new_row = row.copy()
        if prev is None:
            new_row["delta_wind_10m"] = 0.0
            new_row["delta_gusts_10m"] = 0.0
            new_row["delta_wind_925hPa"] = 0.0
        else:
            new_row["delta_wind_10m"]    = safe_value(row, "wind_speed_10m")  - safe_value(prev, "wind_speed_10m")
            new_row["delta_gusts_10m"]   = safe_value(row, "wind_gusts_10m")  - safe_value(prev, "wind_gusts_10m")
            new_row["delta_wind_925hPa"] = safe_value(row, "wind_speed_925hPa") - safe_value(prev, "wind_speed_925hPa")
        enriched.append(new_row)
        prev = row
    return enriched


def hard_veto(row, site):
    reasons, veto_type = [], None
    wind_dir   = safe_value(row, "wind_direction_10m")
    wind_10m   = safe_value(row, "wind_speed_10m")
    gusts      = safe_value(row, "wind_gusts_10m")
    wind_925   = safe_value(row, "wind_speed_925hPa")
    precip     = safe_value(row, "precipitation")
    snowfall   = safe_value(row, "snowfall", 0.0)
    cloud_low  = safe_value(row, "cloud_cover_low")
    delta_p    = safe_value(row, "delta_p_innsbruck_bolzano", 0.0)

    dir_diff = angle_diff_deg(wind_dir, site.launch_dir_center_deg)
    if dir_diff > site.launch_dir_tolerance_deg:
        reasons.append("wind out of sector"); veto_type = "wind"
    if wind_10m > site.launch_wind_max_kmh:
        reasons.append("launch wind above limit"); veto_type = veto_type or "wind"
    if wind_925 > site.wind_925_max_kmh:
        reasons.append("925 wind above limit"); veto_type = veto_type or "wind"
    if gusts > site.gust_max_kmh:
        reasons.append("gusts above limit"); veto_type = veto_type or "gusts"
    if precip > site.precip_max_mm:
        reasons.append("rain"); veto_type = veto_type or "precipitation"
    if snowfall > site.snow_max_cm:
        reasons.append("snow"); veto_type = veto_type or "precipitation"
    if cloud_low >= site.cloud_low_max_pct:
        reasons.append("low cloud at launch"); veto_type = veto_type or "visibility"
    if delta_p > site.foehn_delta_p_max_hpa * 1.20:
        reasons.append("strong foehn pressure gradient"); veto_type = veto_type or "foehn"

    return (len(reasons) > 0), veto_type, reasons


def launch_score(row, site):
    reasons = []
    wind_speed = safe_value(row, "wind_speed_10m")
    gusts      = safe_value(row, "wind_gusts_10m")
    wind_dir   = safe_value(row, "wind_direction_10m")
    cloud_low  = safe_value(row, "cloud_cover_low")

    dir_diff = angle_diff_deg(wind_dir, site.launch_dir_center_deg)
    direction_score = clamp(100.0 * (1.0 - dir_diff / site.launch_dir_tolerance_deg), 0, 100)

    if wind_speed <= 10.0:
        speed_score = 15.0 + (wind_speed / 10.0) * 85.0
    else:
        speed_score = 100.0 * (1.0 - (wind_speed - 10.0) / max(site.launch_wind_max_kmh - 10.0, 1e-9))
    speed_score = clamp(speed_score, 0, 100)

    gust_ok = wind_speed + 5.0
    if gusts <= gust_ok:
        gust_score = 100.0
    elif gusts >= site.gust_max_kmh:
        gust_score = 0.0
    else:
        span = site.gust_max_kmh - gust_ok
        gust_score = 100.0 * (1.0 - (gusts - gust_ok) / span) if span > 0 else 0.0
    gust_score = clamp(gust_score, 0, 100)

    cloud_score = clamp(100.0 * (1.0 - cloud_low / site.cloud_low_max_pct), 0, 100) if site.cloud_low_max_pct > 0 else 100.0

    score = clamp(0.35*direction_score + 0.35*speed_score + 0.15*gust_score + 0.15*cloud_score, 0, 100)

    reasons.append("launch direction well aligned" if dir_diff <= site.launch_dir_tolerance_deg*0.25 else
                   "launch direction acceptable"   if dir_diff <= site.launch_dir_tolerance_deg*0.60 else
                   "launch direction marginal")
    reasons.append("launch wind ideal"  if 8 <= wind_speed <= 12 else
                   "launch wind weak"   if wind_speed < 8         else "launch wind strong")
    reasons.append("gusts well behaved" if gusts <= gust_ok else
                   "gusts borderline"   if gusts < site.gust_max_kmh else "gusts excessive")
    reasons.append("low cloud clear"     if cloud_low <= site.cloud_low_max_pct*0.25 else
                   "some low cloud"      if cloud_low <= site.cloud_low_max_pct*0.60 else
                   "low cloud intrusive")
    return round(score, 1), reasons


def upper_wind_score(row, site):
    reasons = []
    w925, w850, w800, w700 = (safe_value(row, k) for k in
        ["wind_speed_925hPa","wind_speed_850hPa","wind_speed_800hPa","wind_speed_700hPa"])
    d925, d850, d800, d700 = (safe_value(row, k) for k in
        ["wind_direction_925hPa","wind_direction_850hPa","wind_direction_800hPa","wind_direction_700hPa"])

    def peaked(wind, peak, max_w, floor=30.0):
        if wind <= peak:
            s = floor + (wind/peak)*(100-floor)
        else:
            s = 100.0*(1-(wind-peak)/max(max_w-peak,1e-9))
        return clamp(s, 0, 100)

    s925 = peaked(w925, 15, site.wind_925_max_kmh)
    s850 = peaked(w850, 17, site.wind_850_max_kmh)
    s800 = peaked(w800, 18, site.wind_800_max_kmh)
    op   = 0.40*s925 + 0.35*s850 + 0.25*s800

    aloft_start = site.wind_700_max_kmh*0.5
    aloft_penalty = (0.0 if w700 <= aloft_start else
                     30.0 if w700 >= site.wind_700_max_kmh else
                     30.0*(w700-aloft_start)/(site.wind_700_max_kmh-aloft_start))

    speed_jumps = [abs(w850-w925), abs(w800-w850), abs(w700-w800)]
    dir_jumps   = [angle_diff_deg(d850,d925), angle_diff_deg(d800,d850), angle_diff_deg(d700,d800)]

    def spj(j): return 0.0 if j<=8 else 1.0 if j>=20 else (j-8)/12
    def dj(j):  return 0.0 if j<=20 else 1.0 if j>=60 else (j-20)/40

    coh_pen = 35*(0.6*sum(spj(x) for x in speed_jumps)/3 + 0.4*sum(dj(x) for x in dir_jumps)/3)
    score = clamp(op - aloft_penalty - coh_pen, 0, 100)

    def lr(lbl, w, peak, mx):
        return (f"{lbl} wind weak" if w<=peak*0.6 else
                f"{lbl} wind favorable" if w<=peak*1.15 else
                f"{lbl} wind strong" if w<mx else f"{lbl} wind near limit")

    for lbl,w,peak,mx in [("925",w925,15,site.wind_925_max_kmh),
                           ("850",w850,17,site.wind_850_max_kmh),
                           ("800",w800,18,site.wind_800_max_kmh)]:
        reasons.append(lr(lbl,w,peak,mx))
    reasons.append("high-altitude wind moderate" if w700<=aloft_start else
                   "high-altitude wind strong" if w700<site.wind_700_max_kmh else
                   "high-altitude wind very strong")
    reasons.append("vertical profile coherent" if coh_pen<10 else
                   "some vertical shear" if coh_pen<22 else "strong vertical shear")
    return round(score, 1), reasons


def foehn_score(row, site):
    reasons = []
    delta_p = safe_value(row, "delta_p_innsbruck_bolzano", 0.0)
    w925,w850,w800,w700 = (safe_value(row,k) for k in
        ["wind_speed_925hPa","wind_speed_850hPa","wind_speed_800hPa","wind_speed_700hPa"])
    d925,d850,d800,d700 = (safe_value(row,k) for k in
        ["wind_direction_925hPa","wind_direction_850hPa","wind_direction_800hPa","wind_direction_700hPa"])

    p_sc = (0.0 if delta_p<=0 else 100.0 if delta_p>=site.foehn_delta_p_max_hpa else
            100*(delta_p/site.foehn_delta_p_max_hpa))

    def north_sc(d, tol=70.0):
        diff = angle_diff_deg(d, 0.0)
        return 0.0 if diff>=tol else 100*(1-diff/tol)

    def wsup(w, mx): return clamp(100*(w/mx),0,100) if mx>0 else 0.0

    lvls = [(w925,d925,site.wind_925_max_kmh),(w850,d850,site.wind_850_max_kmh),
            (w800,d800,site.wind_800_max_kmh),(w700,d700,site.wind_700_max_kmh)]
    scores = [0.7*north_sc(d)+0.3*wsup(w,mx) for w,d,mx in lvls]
    n_sc = 0.35*scores[0]+0.25*scores[1]+0.20*scores[2]+0.20*scores[3]

    deltas = [w850-w925, w800-w850, w700-w800]
    def gstep(dw): return 20+min(dw,20)/20*80 if dw>0 else 20
    vp_sc = sum(gstep(d) for d in deltas)/3

    score = clamp(0.50*p_sc+0.35*n_sc+0.15*vp_sc, 0, 100)

    reasons.append("weak north-south pressure gradient"     if p_sc<20 else
                   "moderate north-south pressure gradient" if p_sc<60 else
                   "strong north-south pressure gradient")
    for lbl,d in [("700",north_sc(d700)),("850",north_sc(d850)),("925",north_sc(d925))]:
        reasons.append(f"{lbl} flow strongly northerly" if d>=75 else
                       f"{lbl} flow partly northerly"   if d>=40 else
                       f"{lbl} flow not clearly northerly")
    reasons.append("wind increases with height" if vp_sc>=70 else
                   "vertical wind profile partly supportive" if vp_sc>=40 else
                   "vertical wind profile weakly supportive")
    return round(score,1), reasons


def thermal_score(row):
    reasons = []
    hour = int(row["time"][11:13])
    temp_2m  = safe_value(row,"temperature_2m")
    dew_2m   = safe_value(row,"dew_point_2m")
    shortwave= safe_value(row,"shortwave_radiation")
    sunshine = safe_value(row,"sunshine_duration")
    cape     = safe_value(row,"cape")
    cloud_low= safe_value(row,"cloud_cover_low")
    cloud_mid= safe_value(row,"cloud_cover_mid")
    cloud_high=safe_value(row,"cloud_cover_high",0.0)
    rh_925   = safe_value(row,"relative_humidity_925hPa",50.0)
    rh_850   = safe_value(row,"relative_humidity_850hPa",50.0)

    sw_sc = (0.0 if shortwave<=100 else 100.0 if shortwave>=700 else
             100*(shortwave-100)/600)
    sun_sc= (0.0 if sunshine<=0 else 100.0 if sunshine>=2700 else 100*sunshine/2700)
    cl_sc = (0.40*clamp(100*(1-cloud_low/100),0,100)+
             0.45*clamp(100*(1-cloud_mid/100),0,100)+
             0.15*clamp(100*(1-cloud_high/100),0,100))
    heat_sc = clamp(0.45*sw_sc+0.25*sun_sc+0.30*cl_sc,0,100)

    spread = temp_2m - dew_2m
    spread_sc = (0.0 if spread<=0 else 100.0 if spread>=12 else 100*spread/12)
    cape_sc   = (0.0 if cape<=0 else 100.0 if cape>=600 else 100*cape/600)
    resp_sc   = clamp(0.75*spread_sc+0.25*cape_sc,0,100)

    t_sc = clamp(0.70*heat_sc+0.30*resp_sc,0,100)

    cloudbase_m = 0.0 if spread<=0 else 125.0*spread
    cb_band     = ("low" if cloudbase_m<800 else "medium" if cloudbase_m<1800 else "high")

    mean_rh = (rh_925+rh_850)/2
    if hour<9 or hour>19 or t_sc<35 or shortwave<120 or sunshine<600:
        regime = "off"
    elif cloud_mid>=85:
        regime = "tappo"
    elif t_sc>=55:
        regime = ("blue" if spread>=9 and cloud_low<=20 and mean_rh<=45 else
                  "cumulus" if 5<=spread<=10 and mean_rh>=45 and cloud_low<=50 else
                  "blue" if spread>8 else "cumulus")
    else:
        regime = "tappo" if cloud_mid>=70 else "off"

    active = (9<=hour<=19 and t_sc>=55 and shortwave>=180 and sunshine>=900
              and cloud_mid<85 and safe_value(row,"precipitation")<=0.0)

    reasons += (["strong solar input" if shortwave>=500 else
                 "moderate solar input" if shortwave>=250 else "weak solar input"],
                ["good sunshine duration" if sunshine>=2400 else
                 "partial sunshine" if sunshine>=1200 else "limited sunshine"])
    reasons = [reasons[0][0], reasons[1][0]]
    if cloud_mid>=85: reasons.append("too much mid cloud")
    elif cloud_low>=60: reasons.append("substantial low cloud")
    reasons.append("dry boundary layer" if spread>=10 else
                   "moderate temperature-dewpoint spread" if spread>=6 else
                   "humid boundary layer")
    if cape>=300: reasons.append("convective support present")
    reasons.append({"blue":"blue thermals likely","cumulus":"cumulus likely",
                    "tappo":"clouds likely capping development"}.get(regime,
                    "little thermal activity expected"))

    return {
        "thermal_score": round(t_sc,1),
        "thermal_reasons": reasons,
        "thermal_active": active,
        "cloudbase_estimate_m": round(cloudbase_m,0),
        "cloudbase_band": cb_band,
        "thermal_regime": regime,
    }


def risk_score(row, site):
    reasons = []
    cape     = safe_value(row,"cape")
    precip   = safe_value(row,"precipitation")
    cloud_mid= safe_value(row,"cloud_cover_mid")
    cloud_hi = safe_value(row,"cloud_cover_high",0.0)
    rh700    = safe_value(row,"relative_humidity_700hPa",50.0)
    rh600    = safe_value(row,"relative_humidity_600hPa",50.0)
    dw10     = max(safe_value(row,"delta_wind_10m"),0.0)
    dg10     = max(safe_value(row,"delta_gusts_10m"),0.0)
    dw925    = max(safe_value(row,"delta_wind_925hPa"),0.0)

    cape_risk   = clamp(100*cape/800,0,100) if cape>0 else 0.0
    cloud_risk  = clamp(0.65*cloud_mid+0.35*cloud_hi,0,100)
    hum_risk    = clamp((rh700+rh600)/2,0,100)
    prec_risk   = clamp(100*precip,0,100) if precip>0 else 0.0
    storm_risk  = clamp(0.35*cape_risk+0.25*cloud_risk+0.20*hum_risk+0.20*prec_risk,0,100)

    def jsc(d,s,f): return 0.0 if d<=s else 100.0 if d>=f else 100*(d-s)/(f-s)
    wjr = clamp(0.20*jsc(dw10,3,10)+0.35*jsc(dg10,4,12)+0.45*jsc(dw925,3,10),0,100)
    score = clamp(0.60*storm_risk+0.40*wjr,0,100)

    if storm_risk>=65: reasons.append("risk of overdevelopment")
    elif storm_risk>=35: reasons.append("some convective instability")
    if precip>0: reasons.append("precipitation signal present")
    elif cloud_mid>=75: reasons.append("strong mid-cloud build-up")
    if hum_risk>=75: reasons.append("humid upper levels")
    if wjr>=65: reasons.append("wind increasing rapidly")
    elif wjr>=35: reasons.append("wind strengthening")
    if dw925>=5: reasons.append("decollo-level wind rising")
    elif dg10>=5: reasons.append("gusts rising")
    return round(score,1), reasons


def evaluate_hour(row, site):
    veto, veto_type, veto_reasons = hard_veto(row, site)
    f_sc, f_reasons = foehn_score(row, site)

    if veto:
        return {
            "time": row["time"], "veto": True, "veto_type": veto_type,
            "veto_reasons": veto_reasons, "launch_score": None, "launch_reasons": [],
            "upper_wind_score": None, "upper_wind_reasons": [],
            "thermal_score": None, "thermal_reasons": [], "thermal_active": False,
            "cloudbase_estimate_m": None, "cloudbase_band": None, "thermal_regime": None,
            "risk_score": None, "risk_reasons": [],
            "foehn_score": round(f_sc,1), "foehn_reasons": f_reasons,
            "potential_score": None, "risk_penalty": None,
            "foehn_penalty": None, "fly_score": None,
        }

    l_sc,  l_reasons = launch_score(row, site)
    u_sc,  u_reasons = upper_wind_score(row, site)
    th = thermal_score(row)
    r_sc,  r_reasons = risk_score(row, site)

    potential = clamp(0.25*l_sc + 0.35*u_sc + 0.40*th["thermal_score"], 0, 100)
    risk_pen  = 20.0*r_sc/100.0
    foehn_pen = (0.0 if f_sc<=40 else 25.0 if f_sc>=100 else 25*(f_sc-40)/60)
    fly_sc    = clamp(potential - risk_pen - foehn_pen, 0, 100)

    return {
        "time": row["time"], "veto": False, "veto_type": None, "veto_reasons": [],
        "launch_score": round(l_sc,1), "launch_reasons": l_reasons,
        "upper_wind_score": round(u_sc,1), "upper_wind_reasons": u_reasons,
        "thermal_score": round(th["thermal_score"],1), "thermal_reasons": th["thermal_reasons"],
        "thermal_active": th["thermal_active"],
        "cloudbase_estimate_m": th["cloudbase_estimate_m"],
        "cloudbase_band": th["cloudbase_band"],
        "thermal_regime": th["thermal_regime"],
        "risk_score": round(r_sc,1), "risk_reasons": r_reasons,
        "foehn_score": round(f_sc,1), "foehn_reasons": f_reasons,
        "potential_score": round(potential,1),
        "risk_penalty": round(risk_pen,1),
        "foehn_penalty": round(foehn_pen,1),
        "fly_score": round(fly_sc,1),
    }


def round_or_zero(v, n=1): return round(v,n) if v is not None else 0.0
def round0_or_zero(v):     return round(v,0) if v is not None else 0.0


def day_summary(evaluated_hours, day):
    day_rows = [r for r in evaluated_hours if r["time"].startswith(day)]

    def safe_mean(vals):
        v = [x for x in vals if x is not None]
        return sum(v)/len(v) if v else None

    def most_common_nn(vals):
        v = [x for x in vals if x is not None]
        return Counter(v).most_common(1)[0][0] if v else None

    def downgrade(v):
        order = ["bad idea","if you must","meh","not bad","hammer day"]
        return order[max(0, order.index(v)-1)]

    if not day_rows:
        return {"day":day,"verdict":"bad idea","tag":"no-data","best_window":None,
                "best_window_duration_h":0,"mean_fly_score":0.0,"mean_potential_score":0.0,
                "mean_foehn_score":0.0,"mean_risk_score":0.0,"thermal_hours_in_window":0,
                "typical_cloudbase_m":0.0,"dominant_thermal_regime":"off",
                "usable_hours":0,"usable_windows_found":0,"reasons":["no data"]}

    usable = [r for r in day_rows if not r["veto"] and r["fly_score"] is not None and r["fly_score"]>=35]

    if not usable:
        nv = [r for r in day_rows if not r["veto"]]
        mf = safe_mean([r["foehn_score"] for r in nv]) if nv else None
        mr = safe_mean([r["risk_score"] for r in nv]) if nv else None
        tag = ("foehn" if mf and mf>75 else "technical" if mr and mr>60 else
               "capped" if most_common_nn([r.get("thermal_regime") for r in nv])=="tappo" else "short")
        return {"day":day,"verdict":"bad idea","tag":tag,"best_window":None,
                "best_window_duration_h":0,"mean_fly_score":0.0,
                "mean_potential_score":round_or_zero(safe_mean([r["potential_score"] for r in nv])),
                "mean_foehn_score":round_or_zero(mf),"mean_risk_score":round_or_zero(mr),
                "thermal_hours_in_window":0,"typical_cloudbase_m":0.0,
                "dominant_thermal_regime":"off","usable_hours":0,"usable_windows_found":0,
                "reasons":["no usable hours"]}

    usable_times = {r["time"] for r in usable}
    windows, cur = [], []
    for r in day_rows:
        if r["time"] in usable_times: cur.append(r)
        else:
            if cur: windows.append(cur); cur=[]
    if cur: windows.append(cur)
    real = [w for w in windows if len(w)>=2]

    if not real:
        best1 = max(usable, key=lambda x: x["fly_score"])
        return {"day":day,"verdict":"if you must","tag":"short",
                "best_window":(best1["time"][-5:],best1["time"][-5:]),
                "best_window_duration_h":1,
                "mean_fly_score":round_or_zero(best1["fly_score"]),
                "mean_potential_score":round_or_zero(best1["potential_score"]),
                "mean_foehn_score":round_or_zero(best1["foehn_score"]),
                "mean_risk_score":round_or_zero(best1["risk_score"]),
                "thermal_hours_in_window":1 if best1.get("thermal_active") else 0,
                "typical_cloudbase_m":round0_or_zero(best1.get("cloudbase_estimate_m")),
                "dominant_thermal_regime":best1.get("thermal_regime") or "off",
                "usable_hours":len(usable),"usable_windows_found":0,
                "reasons":["only isolated usable hour found"]}

    wsums = []
    for w in real:
        mf  = safe_mean([r["fly_score"] for r in w])
        mp  = safe_mean([r["potential_score"] for r in w])
        mfn = safe_mean([r["foehn_score"] for r in w])
        mr  = safe_mean([r["risk_score"] for r in w])
        dur = len(w)
        val = 0.60*mf + 0.20*min(dur/5,1)*100 + 0.20*(mp or 0)
        wsums.append({"rows":w,"start":w[0]["time"][-5:],"end":w[-1]["time"][-5:],
                      "duration":dur,"mean_fly":mf,"mean_potential":mp,
                      "mean_foehn":mfn,"mean_risk":mr,
                      "thermal_hours":sum(1 for r in w if r.get("thermal_active")),
                      "mean_cloudbase":safe_mean([r.get("cloudbase_estimate_m") for r in w]),
                      "dominant_regime":most_common_nn([r.get("thermal_regime") for r in w]),
                      "window_value":val})

    best = max(wsums, key=lambda x: x["window_value"])
    mf,mp,mfn,mr,dur = (best["mean_fly"],best["mean_potential"],
                         best["mean_foehn"] or 0.0, best["mean_risk"] or 0.0, best["duration"])

    verdict = ("if you must" if mf<45 else "meh" if mf<58 else "not bad" if mf<72 else
               "hammer day" if dur>=4 and mp is not None and mp>=70 else "not bad")
    if mfn>90:                                           verdict = downgrade(verdict)
    elif mfn>80 and verdict in ["not bad","hammer day"]: verdict = downgrade(verdict)
    if mr>75 and verdict in ["meh","not bad","hammer day"]: verdict = downgrade(verdict)

    tag = ("short" if dur<=2 else "stable")
    dr  = best["dominant_regime"]
    tag = {"blue":"blue","cumulus":"cumulus","tappo":"capped"}.get(dr, tag)
    if mr>60: tag="technical"
    if mfn>75: tag="foehn"

    reasons = [f"best window {best['start']}–{best['end']}",
               f"mean fly score {mf:.1f}" if mf else "",
               f"window duration {dur} h"]
    if best["thermal_hours"]>0:
        reasons.append(f"{best['thermal_hours']} thermal-active hours in best window")
    if mfn>90: reasons.append("very strong foehn signal degraded the day")
    if mr>75:  reasons.append("risk/technicality degraded the day")
    reasons = [r for r in reasons if r]

    return {"day":day,"verdict":verdict,"tag":tag,
            "best_window":(best["start"],best["end"]),
            "best_window_duration_h":dur,
            "mean_fly_score":round_or_zero(mf),"mean_potential_score":round_or_zero(mp),
            "mean_foehn_score":round_or_zero(mfn),"mean_risk_score":round_or_zero(mr),
            "thermal_hours_in_window":best["thermal_hours"],
            "typical_cloudbase_m":round0_or_zero(best["mean_cloudbase"]),
            "dominant_thermal_regime":dr or "off",
            "usable_hours":len(usable),"usable_windows_found":len(real),
            "reasons":reasons}


# ──────────────────────────────────────────────────────────────────────────────
# VISUALISATION
# ──────────────────────────────────────────────────────────────────────────────
VETO_COLORS = {
    "wind": "#EF5350", "precipitation": "#42A5F5", "foehn": "#FFA726",
    "visibility": "#78909C", "gusts": "#EC407A", None: "#66BB6A",
}
SCORE_COLORS = {
    "launch": "#4FC3F7", "upper_wind": "#81C784",
    "thermal": "#FFD54F", "risk": "#EF9A9A", "foehn_line": "#FFA726",
}
VERDICT_COLORS = {
    "hammer day": "#69F0AE", "not bad": "#AED581",
    "meh": "#FFD740", "if you must": "#FFAB40", "bad idea": "#FF5252",
}
FLY_CMAP = plt.cm.RdYlGn
BG, PANEL_BG, TEXT, GRID_C = "#1C1C2E", "#252540", "#E0E0E0", "#383860"


def _v(val, default=0.0):
    return val if val is not None else default

def _raw(row, rbt, key, default=0.0):
    return _v(rbt.get(row["time"], {}).get(key), default)

def _style(ax, x, labels):
    ax.set_facecolor(PANEL_BG)
    ax.tick_params(colors=TEXT, labelsize=8)
    ax.xaxis.label.set_color(TEXT); ax.yaxis.label.set_color(TEXT)
    for sp in ax.spines.values(): sp.set_color(GRID_C)
    ax.grid(axis="y", color=GRID_C, linewidth=0.5, linestyle="--", zorder=0)
    ax.set_xlim(-0.5, len(x)-0.5)
    ax.set_xticks(x); ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=7)

def _style_twin(ax):
    ax.set_facecolor(PANEL_BG); ax.tick_params(labelsize=7)
    for sp in ax.spines.values(): sp.set_color(GRID_C)


def make_flight_fig(day, evaluated_all, rows_all, site):
    rbt = {r["time"]: r for r in rows_all}
    hrs = [h for h in evaluated_all
           if h["time"].startswith(day) and 6 <= int(h["time"][11:13]) <= 20]
    if not hrs:
        return None

    smry   = day_summary(evaluated_all, day)
    labels = [h["time"][11:16] for h in hrs]
    x      = np.arange(len(hrs))

    fly_sc     = [_v(h["fly_score"])        for h in hrs]
    launch_sc  = [_v(h["launch_score"])     for h in hrs]
    upper_sc   = [_v(h["upper_wind_score"]) for h in hrs]
    thermal_sc = [_v(h["thermal_score"])    for h in hrs]
    risk_sc    = [_v(h["risk_score"])       for h in hrs]
    foehn_sc   = [_v(h["foehn_score"])      for h in hrs]
    cloudbase  = [h["cloudbase_estimate_m"] for h in hrs]

    wind_10m  = [_raw(h, rbt, "wind_speed_10m")    for h in hrs]
    gusts_10m = [_raw(h, rbt, "wind_gusts_10m")    for h in hrs]
    wind_925  = [_raw(h, rbt, "wind_speed_925hPa") for h in hrs]
    wind_850  = [_raw(h, rbt, "wind_speed_850hPa") for h in hrs]
    wind_700  = [_raw(h, rbt, "wind_speed_700hPa") for h in hrs]
    precip    = [_raw(h, rbt, "precipitation")     for h in hrs]
    cc_low    = [_raw(h, rbt, "cloud_cover_low")   for h in hrs]
    cc_mid    = [_raw(h, rbt, "cloud_cover_mid")   for h in hrs]
    cc_high   = [_raw(h, rbt, "cloud_cover_high")  for h in hrs]

    fig = plt.figure(figsize=(16, 14))
    fig.patch.set_facecolor(BG)
    gs   = GridSpec(4, 1, figure=fig, hspace=0.65, top=0.88, bottom=0.05, left=0.07, right=0.92)
    axes = [fig.add_subplot(gs[i]) for i in range(4)]
    for ax in axes: _style(ax, x, labels)

    # header
    verdict  = smry.get("verdict","?")
    tag      = smry.get("tag","")
    win      = smry.get("best_window")
    cb_m     = smry.get("typical_cloudbase_m")
    mean_fly = smry.get("mean_fly_score",0)
    mean_foe = smry.get("mean_foehn_score",0)
    mean_rsk = smry.get("mean_risk_score",0)
    usable_h = smry.get("usable_hours",0)
    vcol     = VERDICT_COLORS.get(verdict, TEXT)
    win_str  = f"  ·  best window: {win[0]}–{win[1]}" if win else "  ·  no usable window"
    cb_str   = f"  ·  cloudbase ≈ {int(cb_m)} m" if cb_m else ""

    fig.text(0.01, 0.955, f"{site.name}  —  {day}", fontsize=11, color=TEXT, fontweight="bold", va="top")
    fig.text(0.01, 0.925, verdict.upper(), fontsize=24, color=vcol, fontweight="bold", va="top")
    if tag:
        fig.text(0.22, 0.930, f"[{tag}]", fontsize=12, color="#FFA726", fontweight="bold", va="top")
    fig.text(0.37, 0.932,
             f"fly {mean_fly:.0f}  ·  foehn {mean_foe:.0f}  ·  risk {mean_rsk:.0f}"
             f"  ·  usable h: {usable_h}{win_str}{cb_str}",
             fontsize=9, color=TEXT, va="top")
    reasons = smry.get("reasons",[])
    if reasons:
        fig.text(0.37, 0.910, "  ·  ".join(reasons), fontsize=7.5, color="#9E9E9E", va="top")

    # ── P1: status strip ──────────────────────────────────────────────────────
    ax1 = axes[0]
    bar_colors = [VETO_COLORS.get(h["veto_type"],"#888") if h["veto"]
                  else FLY_CMAP(_v(h["fly_score"])/100) for h in hrs]
    ax1.bar(x, [100]*len(x), color=bar_colors, width=0.85, alpha=0.90, zorder=2)

    for i, h in enumerate(hrs):
        lines = [f"G {gusts_10m[i]:.0f}", f"925 {wind_925[i]:.0f}"]
        if precip[i] > 0.05: lines.append(f"P {precip[i]:.1f}")
        ax1.text(i, 97, "\n".join(lines), ha="center", va="top",
                 fontsize=5.5, color="white", alpha=0.85,
                 linespacing=1.4, fontfamily="monospace", zorder=4)

    fx = [i for i,h in enumerate(hrs) if not h["veto"] and _v(h["fly_score"])>0]
    fs = [_v(h["fly_score"]) for h in hrs if not h["veto"] and _v(h["fly_score"])>0]
    if fx: ax1.plot(fx, fs, "o-", color="white", lw=1.5, ms=5, alpha=0.9, zorder=5, label="fly score")

    ax1.set_ylim(0,105); ax1.set_ylabel("fly score", fontsize=8)
    ax1.set_title("Status & fly score", color=TEXT, fontsize=9, pad=5, loc="left")
    ax1.legend(handles=[mpatches.Patch(color=c, label=lbl or "flyable")
               for lbl,c in VETO_COLORS.items()],
               loc="upper right", fontsize=7, ncol=3,
               facecolor=PANEL_BG, labelcolor=TEXT, edgecolor=GRID_C)

    # ── P2: fly score + component scores ─────────────────────────────────────
    ax2 = axes[1]
    ax2.fill_between(x, 0, fly_sc, color="white", alpha=0.08, zorder=1)
    ax2.plot(x, fly_sc, color="white", lw=2.5, alpha=0.85, zorder=5,
             label="fly score", marker="o", ms=4)
    w = 0.20
    ax2.bar(x-1.5*w, launch_sc,  width=w, label="launch",     color=SCORE_COLORS["launch"],     alpha=0.80, zorder=3)
    ax2.bar(x-0.5*w, upper_sc,   width=w, label="upper wind", color=SCORE_COLORS["upper_wind"], alpha=0.80, zorder=3)
    ax2.bar(x+0.5*w, thermal_sc, width=w, label="thermal",    color=SCORE_COLORS["thermal"],    alpha=0.80, zorder=3)
    ax2.bar(x+1.5*w, risk_sc,    width=w, label="risk",       color=SCORE_COLORS["risk"],       alpha=0.80, zorder=3)
    ax2r = ax2.twinx(); _style_twin(ax2r)
    ax2r.plot(x, foehn_sc, color=SCORE_COLORS["foehn_line"], lw=1.8,
              linestyle="--", marker="D", ms=3, label="foehn", zorder=4)
    ax2r.set_ylim(0,100); ax2r.tick_params(colors="#FFA726", labelsize=7)
    ax2r.set_ylabel("foehn score", color="#FFA726", fontsize=7)
    ax2.set_ylim(0,100); ax2.set_ylabel("score", fontsize=8)
    ax2.set_title("Fly score & component scores", color=TEXT, fontsize=9, pad=5, loc="left")
    hl,ll = ax2.get_legend_handles_labels(); hr,lr = ax2r.get_legend_handles_labels()
    ax2.legend(hl+hr, ll+lr, loc="upper left", fontsize=7, ncol=6,
               facecolor=PANEL_BG, labelcolor=TEXT, edgecolor=GRID_C)

    # ── P3: wind by level ─────────────────────────────────────────────────────
    ax3 = axes[2]
    ax3.fill_between(x, wind_10m, gusts_10m, alpha=0.15, color="#80DEEA", label="gust range", zorder=1)
    ax3.plot(x, wind_10m,  color="#80DEEA", lw=1.8, label="10m",        marker="o", ms=3, zorder=3)
    ax3.plot(x, gusts_10m, color="#80DEEA", lw=1.0, linestyle=":",      label="gusts 10m",  zorder=3)
    ax3.plot(x, wind_925,  color="#4FC3F7", lw=1.8, label="925 hPa",    zorder=3)
    ax3.plot(x, wind_850,  color="#7986CB", lw=1.8, label="850 hPa",    zorder=3)
    ax3.plot(x, wind_700,  color="#CE93D8", lw=1.8, label="700 hPa",    zorder=3)
    ax3.axhline(site.launch_wind_max_kmh, color="#FF5252", lw=1.2, linestyle=":", zorder=4,
                label=f"launch limit ({site.launch_wind_max_kmh:.0f})")
    ax3.axhline(site.wind_925_max_kmh,    color="#FF8A65", lw=1.2, linestyle=":", zorder=4,
                label=f"925 limit ({site.wind_925_max_kmh:.0f})")
    ax3.set_ylabel("km/h", fontsize=8)
    ax3.set_title("Wind speed by level", color=TEXT, fontsize=9, pad=5, loc="left")
    ax3.legend(loc="upper right", fontsize=7, ncol=4,
               facecolor=PANEL_BG, labelcolor=TEXT, edgecolor=GRID_C)

    # ── P4: clouds + precip + cloudbase ──────────────────────────────────────
    ax4 = axes[3]
    ax4.stackplot(x, cc_high, cc_mid, cc_low,
                  labels=["cloud high","cloud mid","cloud low"],
                  colors=["#455A64","#546E7A","#607D8B"], alpha=0.75, zorder=1)
    ax4.set_ylim(0,100); ax4.set_ylabel("cloud cover %", fontsize=8)
    ax4.set_title("Cloud cover, precipitation & cloudbase", color=TEXT, fontsize=9, pad=5, loc="left")
    ax4r = ax4.twinx(); _style_twin(ax4r)
    ax4r.bar(x, precip, color="#64B5F6", alpha=0.75, width=0.5, label="precip (mm/h)", zorder=3)
    ax4r.tick_params(colors="#64B5F6", labelsize=7); ax4r.set_ylabel("precip (mm/h)", color="#64B5F6", fontsize=7)
    ax4b = ax4.twinx()
    ax4b.spines["right"].set_position(("axes", 1.07)); _style_twin(ax4b)
    cb_clean = [c if c is not None else float("nan") for c in cloudbase]
    ax4b.plot(x, cb_clean, color="#FFCC02", lw=1.8, linestyle="-.",
              marker="s", ms=3, label="cloudbase (m)", zorder=4)
    ax4b.tick_params(colors="#FFCC02", labelsize=7); ax4b.set_ylabel("cloudbase (m)", color="#FFCC02", fontsize=7)
    h4,l4 = ax4.get_legend_handles_labels()
    h4r,l4r = ax4r.get_legend_handles_labels()
    h4b,l4b = ax4b.get_legend_handles_labels()
    ax4.legend(h4+h4r+h4b, l4+l4r+l4b, loc="upper right", fontsize=7, ncol=3,
               facecolor=PANEL_BG, labelcolor=TEXT, edgecolor=GRID_C)

    return fig


# ──────────────────────────────────────────────────────────────────────────────
# MAIN UI
# ──────────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
body, .stApp { background-color: #1C1C2E; color: #E0E0E0; }
.stTabs [data-baseweb="tab-list"] { gap: 8px; }
.stTabs [data-baseweb="tab"]      { background-color: #252540; border-radius: 6px; padding: 6px 18px; color: #E0E0E0; }
.stTabs [aria-selected="true"]    { background-color: #383860 !important; }
</style>
""", unsafe_allow_html=True)

# session state
if "evaluated" not in st.session_state:
    st.session_state.evaluated = None
    st.session_state.rows      = None
    st.session_state.days      = None

if fetch_btn:
    with st.spinner("Fetching forecast from Open-Meteo…"):
        try:
            fc       = fetch_forecast(SITE.latitude, SITE.longitude, SITE.timezone, SITE.model, forecast_days)
            ps       = fetch_foehn_pressure_series(SITE.timezone, forecast_days)
            rows     = hourly_rows(fc)
            rows     = enrich_rows_with_foehn_pressure(rows, ps)
            rows     = enrich_rows_with_wind_deltas(rows)
            evaluated = [evaluate_hour(r, SITE) for r in rows]
            days      = sorted({r["time"][:10] for r in evaluated})
            st.session_state.evaluated = evaluated
            st.session_state.rows      = rows
            st.session_state.days      = days
            st.success("Forecast loaded ✓")
        except Exception as e:
            st.error(f"Error fetching data: {e}")

if st.session_state.evaluated is None:
    st.info("👈 Configure the site in the sidebar, then click **Fetch forecast**.")
    st.stop()

evaluated = st.session_state.evaluated
rows      = st.session_state.rows
days      = st.session_state.days

# quick summary cards
summaries = {d: day_summary(evaluated, d) for d in days}

cols = st.columns(len(days))
for col, d in zip(cols, days):
    sm = summaries[d]
    vc = VERDICT_COLORS.get(sm["verdict"], "#E0E0E0")
    col.markdown(
        f"""<div style="background:#252540;border-radius:10px;padding:14px 10px;text-align:center;">
        <div style="font-size:11px;color:#9E9E9E;">{d}</div>
        <div style="font-size:22px;font-weight:bold;color:{vc};">{sm['verdict'].upper()}</div>
        <div style="font-size:12px;color:#FFA726;">[{sm['tag']}]</div>
        <div style="font-size:11px;color:#E0E0E0;margin-top:4px;">
          fly {sm['mean_fly_score']:.0f} · {sm['usable_hours']} h usable
        </div>
        </div>""",
        unsafe_allow_html=True,
    )

st.markdown("<br>", unsafe_allow_html=True)

# per-day tabs with charts
tabs = st.tabs([f"📅 {d}" for d in days])
for tab, d in zip(tabs, days):
    with tab:
        fig = make_flight_fig(d, evaluated, rows, SITE)
        if fig:
            st.pyplot(fig, use_container_width=True)
            plt.close(fig)
        else:
            st.warning(f"No data for {d}")

        # detail table for this day
        with st.expander("🔍 Hour-by-hour detail"):
            day_hrs = [h for h in evaluated if h["time"].startswith(d)
                       and 6 <= int(h["time"][11:13]) <= 20]
            import pandas as pd
            df = pd.DataFrame([{
                "time":         h["time"][11:16],
                "veto":         "✗ "+h["veto_type"] if h["veto"] else "✓",
                "fly":          _v(h["fly_score"]),
                "launch":       _v(h["launch_score"]),
                "upper_wind":   _v(h["upper_wind_score"]),
                "thermal":      _v(h["thermal_score"]),
                "risk":         _v(h["risk_score"]),
                "foehn":        _v(h["foehn_score"]),
                "cloudbase":    h["cloudbase_estimate_m"] or "",
                "regime":       h["thermal_regime"] or "",
            } for h in day_hrs])
            st.dataframe(df, use_container_width=True, hide_index=True)
