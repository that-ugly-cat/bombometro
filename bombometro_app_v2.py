"""
bombometro · app.py
===================
Streamlit Cloud frontend — Plotly charts.
All domain logic lives in core.py — this file only handles UI and charts.
"""

import pandas as pd
import plotly.colors as pc
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from core import (
    SITE_PRESETS,
    SiteConfig,
    day_summary,
    fetch_foehn_pressure_series,
    fetch_forecast,
    get_sun_times,
    run_pipeline,
    wind_dir_label,
)
from advisor import (
    SECRET_QUESTION,
    build_day_context,
    check_secret,
    get_advisory,
)

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
# CACHED FETCH WRAPPERS  (ttl = 30 min)
# ──────────────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=1800, show_spinner=False)
def _fetch_forecast(lat, lon, tz, model, forecast_days):
    dummy = SiteConfig(
        name="", latitude=lat, longitude=lon, timezone=tz, model=model,
        launch_dir_center_deg=0, launch_dir_tolerance_deg=0,
        launch_wind_min_kmh=0,   launch_wind_max_kmh=0,
        gust_max_kmh=0,          wind_925_max_kmh=0,
        wind_850_max_kmh=0,      wind_800_max_kmh=0,
        wind_700_max_kmh=0,      foehn_delta_p_max_hpa=0,
        foehn_north_lat=0,       foehn_north_lon=0,
        foehn_south_lat=0,       foehn_south_lon=0,
        precip_max_mm=0,         snow_max_cm=0,
        cloud_low_max_pct=0,     cloud_cover_low_bad=0,
        cloud_cover_mid_bad=0,   shortwave_good=0,
        dewpoint_spread_good=0,  cape_max=0,
    )
    return fetch_forecast(dummy, forecast_days)


@st.cache_data(ttl=1800, show_spinner=False)
def _fetch_foehn(north_lat, north_lon, south_lat, south_lon, tz, forecast_days):
    return fetch_foehn_pressure_series(north_lat, north_lon, south_lat, south_lon, tz, forecast_days)


@st.cache_data(ttl=3600, show_spinner=False)
def _cached_advisory(day_context: str, api_key: str) -> str:
    """Cache advisory by (context, key) — identical inputs reuse the same LLM response."""
    return get_advisory(day_context, api_key)

# ──────────────────────────────────────────────────────────────────────────────
# PALETTE
# ──────────────────────────────────────────────────────────────────────────────
VETO_COLORS = {
    "wind":          "#EF5350",
    "precipitation": "#42A5F5",
    "foehn":         "#FFA726",
    "visibility":    "#78909C",
    "gusts":         "#EC407A",
}
VERDICT_COLORS = {
    "hammer day":  "#69F0AE",
    "not bad":     "#AED581",
    "meh":         "#FFD740",
    "if you must": "#FFAB40",
    "bad idea":    "#FF5252",
}
VERDICT_EMOJI = {
    "hammer day":  "🤩",
    "not bad":     "😁",
    "meh":         "😐",
    "if you must": "😬",
    "bad idea":    "💀",
}
BG       = "#1C1C2E"
PANEL_BG = "#252540"
TEXT     = "#E0E0E0"
GRID_C   = "#383860"

# ──────────────────────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────────────────────

def _v(val, default=0.0):
    return val if val is not None else default


def _raw(row, rbt, key, default=0.0):
    return _v(rbt.get(row["time"], {}).get(key), default)


def _fly_color(score: float) -> str:
    """Map 0-100 fly score → RdYlGn hex color."""
    return pc.sample_colorscale("RdYlGn", [max(0.0, min(1.0, score / 100.0))])[0]


def _axis(gridcolor=GRID_C, zeroline=False, **kw):
    return dict(gridcolor=gridcolor, zeroline=zeroline,
                tickfont=dict(size=10, color=TEXT),
                title_font=dict(size=11, color=TEXT), **kw)


def _fmt_reasons(reasons_list) -> str:
    """Join a reasons list into a single display string."""
    items = [str(x) for x in (reasons_list or [])]
    return " · ".join(items) if items else "—"


def _alerts_str(h: dict) -> str:
    """Concise alert string for the hour-by-hour table (negative/risk reasons only)."""
    parts: list = []
    if h["veto"]:
        parts.extend(h.get("veto_reasons") or [])
    else:
        if _v(h.get("launch_score")) < 60:
            parts.extend(h.get("launch_reasons") or [])
        if _v(h.get("upper_wind_score")) < 60:
            parts.extend(h.get("upper_wind_reasons") or [])
        if _v(h.get("risk_score")) > 20:
            parts.extend(h.get("risk_reasons") or [])
        if _v(h.get("foehn_score")) > 30:
            parts.extend(h.get("foehn_reasons") or [])
        rpen = _v(h.get("risk_penalty"))
        fpen = _v(h.get("foehn_penalty"))
        fatt = _v(h.get("foehn_attenuation"))
        if rpen > 0:
            parts.append(f"risk penalty −{rpen:.1f}")
        if fpen > 0:
            parts.append(f"foehn penalty −{fpen:.1f}")
        if fatt > 0:
            parts.append(f"foehn attenuated by thermals −{fatt:.1f}")
    return " · ".join(str(p) for p in parts) if parts else ""

# ──────────────────────────────────────────────────────────────────────────────
# MAIN CHART  — one Plotly figure, 4 subplots, shared x-axis
# ──────────────────────────────────────────────────────────────────────────────

def make_day_chart(day: str, evaluated_all, rows_all, site: SiteConfig,
                   sun_times: dict = None):
    """Return a single Plotly figure with 7 vertically-stacked subplots."""
    rbt  = {r["time"]: r for r in rows_all}
    hrs  = [h for h in evaluated_all
            if h["time"].startswith(day) and 6 <= int(h["time"][11:13]) <= 20]
    if not hrs:
        return None

    smry = day_summary(evaluated_all, day)
    lbl  = [h["time"][11:13] for h in hrs]

    # ── score series ──
    fly_sc      = [_v(h["fly_score"])        for h in hrs]
    potential_sc= [_v(h["potential_score"])  for h in hrs]   # always populated
    launch_sc   = [_v(h["launch_score"])     for h in hrs]
    upper_sc    = [_v(h["upper_wind_score"]) for h in hrs]
    thermal_sc  = [_v(h["thermal_score"])    for h in hrs]
    risk_sc     = [_v(h["risk_score"])       for h in hrs]
    foehn_sc    = [_v(h["foehn_score"])      for h in hrs]
    cloudbase   = [h["cloudbase_estimate_m"] for h in hrs]   # always populated

    # ── raw meteo ──
    wind_10m  = [_raw(h, rbt, "wind_speed_10m")      for h in hrs]
    gusts_10m = [_raw(h, rbt, "wind_gusts_10m")      for h in hrs]
    dir_10m   = [_raw(h, rbt, "wind_direction_10m")  for h in hrs]
    wind_925  = [_raw(h, rbt, "wind_speed_925hPa")   for h in hrs]
    dir_925   = [_raw(h, rbt, "wind_direction_925hPa") for h in hrs]
    wind_850  = [_raw(h, rbt, "wind_speed_850hPa")   for h in hrs]
    dir_850   = [_raw(h, rbt, "wind_direction_850hPa") for h in hrs]
    wind_700  = [_raw(h, rbt, "wind_speed_700hPa")   for h in hrs]
    dir_700   = [_raw(h, rbt, "wind_direction_700hPa") for h in hrs]
    precip    = [_raw(h, rbt, "precipitation")       for h in hrs]
    cc_low    = [_raw(h, rbt, "cloud_cover_low")     for h in hrs]
    cc_mid    = [_raw(h, rbt, "cloud_cover_mid")     for h in hrs]
    cc_high   = [_raw(h, rbt, "cloud_cover_high")    for h in hrs]

    # ── thermal raw ──
    shortwave_vals  = [_raw(h, rbt, "shortwave_radiation")                                  for h in hrs]
    lapse_rate_vals = [_raw(h, rbt, "temperature_2m") - _raw(h, rbt, "temperature_700hPa") for h in hrs]
    spread_vals     = [_raw(h, rbt, "temperature_2m") - _raw(h, rbt, "dew_point_2m")       for h in hrs]

    # ── foehn pressure gradient ──
    dp_vals = [_raw(h, rbt, "delta_p_foehn") for h in hrs]

    # ── atmospheric profile ──
    rh_925_vals = [_raw(h, rbt, "relative_humidity_925hPa") for h in hrs]
    rh_850_vals = [_raw(h, rbt, "relative_humidity_850hPa") for h in hrs]
    rh_800_vals = [_raw(h, rbt, "relative_humidity_800hPa") for h in hrs]
    rh_700_vals = [_raw(h, rbt, "relative_humidity_700hPa") for h in hrs]
    fl_vals     = [_raw(h, rbt, "freezing_level_height")    for h in hrs]  # m asl

    t_2m  = [_raw(h, rbt, "temperature_2m")      for h in hrs]
    t_925 = [_raw(h, rbt, "temperature_925hPa")  for h in hrs]
    t_850 = [_raw(h, rbt, "temperature_850hPa")  for h in hrs]
    t_700 = [_raw(h, rbt, "temperature_700hPa")  for h in hrs]
    # inversion = temperature INCREASES with altitude (delta > 0 → warmer aloft)
    inv_sfc_925 = [t9 - t2 for t2, t9 in zip(t_2m,  t_925)]
    inv_925_850 = [t8 - t9 for t9, t8 in zip(t_925, t_850)]
    inv_850_700 = [t7 - t8 for t8, t7 in zip(t_850, t_700)]

    # ── compass labels ──
    lbl_10m  = [f"{wind_dir_label(d)} {v:.0f}" for d, v in zip(dir_10m,  wind_10m)]
    lbl_925  = [f"{wind_dir_label(d)} {v:.0f}" for d, v in zip(dir_925,  wind_925)]
    lbl_850  = [f"{wind_dir_label(d)} {v:.0f}" for d, v in zip(dir_850,  wind_850)]
    lbl_700  = [f"{wind_dir_label(d)} {v:.0f}" for d, v in zip(dir_700,  wind_700)]
    lbl_gust = [f"{wind_dir_label(d)} {v:.0f}" for d, v in zip(dir_10m,  gusts_10m)]

    # ── figure skeleton ──
    fig = make_subplots(
        rows=7, cols=1,
        shared_xaxes=True,
        row_heights=[0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2],
        vertical_spacing=0.08,
        specs=[[{"secondary_y": True}]] * 7,
        subplot_titles=[
            "🚦  Status & fly score",
            "📊  Component scores",
            "🌡️  Thermal activity",
            "🧊  Atmospheric profile  (RH · freezing level · inversions)",
            "☁️  Cloud cover & precipitation",
            "🌬️  Foehn pressure gradient (hPa)",
            "💨  Wind by level  (km/h)",
        ],
    )

    # ─────────────────────────────────────────────────────────────────────────
    # ROW 1 — status bars + fly-score line
    # ─────────────────────────────────────────────────────────────────────────
    bar_colors = [
        VETO_COLORS.get(h["veto_type"], "#888888") if h["veto"]
        else _fly_color(_v(h["fly_score"]))
        for h in hrs
    ]

    hover_txt = []
    for i, h in enumerate(hrs):
        if h["veto"]:
            vr = h.get("veto_reasons") or [h["veto_type"] or "?"]
            # include "foehn" label only when there is active foehn influence, no full reasons
            if h.get("foehn_score", 0) and _v(h.get("foehn_score")) > 30 and "foehn" not in vr:
                vr = list(vr) + ["foehn"]
            top = (f"<b>⛔ {(h['veto_type'] or 'veto').upper()}</b>"
                   f"<br>{' · '.join(str(x) for x in vr)}")
        else:
            top = (
                f"<b>fly {_v(h['fly_score']):.0f}</b>"
                f"  launch {_v(h['launch_score']):.0f}"
                f"  UW {_v(h['upper_wind_score']):.0f}"
                f"  thermal {_v(h['thermal_score']):.0f}"
                f"  risk {_v(h['risk_score']):.0f}"
            )
            if cloudbase[i] is not None:
                top += (f"<br>cloudbase ≈ {int(cloudbase[i])} m"
                        f"  [{h.get('thermal_regime','')}]")
        met = (
            f"<br><span style='color:#9E9E9E'>"
            f"10m {lbl_10m[i]} km/h  "
            f"Gu {lbl_gust[i]} km/h  "
            f"925 {lbl_925[i]} km/h  "
            f"P {precip[i]:.1f} mm/h</span>"
        )
        hover_txt.append(top + met)

    fig.add_trace(
        go.Bar(
            x=lbl, y=[100] * len(hrs),
            marker=dict(color=bar_colors, line=dict(width=0)),
            hovertext=hover_txt, hoverinfo="text",
            showlegend=False, name="status",
        ),
        row=1, col=1,
    )

    # potential score shadow — continuous, bridges veto gaps deliberately
    fig.add_trace(
        go.Scatter(
            x=lbl, y=potential_sc, name="potential (no veto)",
            mode="lines",
            line=dict(color="#757575", dash="dot", width=1.5),
            legend="legend",
            hovertemplate="potential: <b>%{y:.0f}</b><extra></extra>",
        ),
        row=1, col=1,
    )

    # fly-score line — gaps on vetoed hours
    fly_y_r1 = [h["fly_score"] if not h["veto"] else None for h in hrs]
    fig.add_trace(
        go.Scatter(
            x=lbl, y=fly_y_r1, name="fly score",
            mode="lines+markers",
            line=dict(color="white", width=2.5),
            marker=dict(size=7, color="white", line=dict(color=PANEL_BG, width=1.5)),
            connectgaps=False,
            legend="legend",
            hovertemplate="fly score: <b>%{y:.0f}</b><extra></extra>",
        ),
        row=1, col=1,
    )

    # ─────────────────────────────────────────────────────────────────────────
    # ROW 2 — fly-score area + component bars + foehn line (secondary y)
    # ─────────────────────────────────────────────────────────────────────────

    # potential score shadow — same continuous line, drawn behind the fly area
    fig.add_trace(
        go.Scatter(
            x=lbl, y=potential_sc, name="potential (no veto)",
            mode="lines",
            line=dict(color="#757575", dash="dot", width=1.5),
            showlegend=False,
            hovertemplate="potential: <b>%{y:.0f}</b><extra></extra>",
        ),
        row=2, col=1,
    )

    # fly score area — same gap logic: None for vetoed hours
    fly_y_r2 = [h["fly_score"] if not h["veto"] else None for h in hrs]
    fig.add_trace(
        go.Scatter(
            x=lbl, y=fly_y_r2,
            fill="tozeroy", fillcolor="rgba(255,255,255,0.06)",
            line=dict(color="white", width=2.5),
            mode="lines+markers",
            marker=dict(size=5, color="white", line=dict(color=PANEL_BG, width=1)),
            connectgaps=False,
            name="fly score", showlegend=False,
            hovertemplate="fly score: <b>%{y:.0f}</b><extra></extra>",
        ),
        row=2, col=1,
    )

    # Component bars: full opacity for flyable hours, ghost (35%) for vetoed.
    # Per-bar rgba colors let us distinguish vetoed bars without hiding them.
    _RGB = {"#4FC3F7": (79,195,247), "#81C784": (129,199,132),
            "#FFD54F": (255,213,79),  "#EF9A9A": (239,154,154)}

    for name, data, hex_c in [
        ("launch",     launch_sc,  "#4FC3F7"),
        ("upper wind", upper_sc,   "#81C784"),
        ("thermal",    thermal_sc, "#FFD54F"),
        ("risk",       risk_sc,    "#EF9A9A"),
    ]:
        rc, g, b = _RGB[hex_c]
        bar_colors = [
            f"rgba({rc},{g},{b},0.82)" if not h["veto"]
            else f"rgba({rc},{g},{b},0.30)"
            for h in hrs
        ]
        fig.add_trace(
            go.Bar(
                x=lbl, y=data, name=name,
                marker=dict(color=bar_colors, line=dict(width=0)),
                legend="legend2",
                hovertemplate=f"{name}: <b>%{{y:.0f}}</b><extra></extra>",
            ),
            row=2, col=1,
        )

    fig.add_trace(
        go.Scatter(
            x=lbl, y=foehn_sc, name="foehn",
            mode="lines+markers",
            line=dict(color="#FFA726", dash="dash", width=1.8),
            marker=dict(size=5, symbol="diamond", color="#FFA726"),
            legend="legend2",
            hovertemplate="foehn: <b>%{y:.0f}</b><extra></extra>",
        ),
        row=2, col=1, secondary_y=True,
    )

    # ─────────────────────────────────────────────────────────────────────────
    # ROW 3 — thermal activity
    # ─────────────────────────────────────────────────────────────────────────

    # regime-colored background (sole bar in this subplot → no grouping issue)
    _REGIME_BG = {
        "blue":    "rgba(79,195,247,0.13)",
        "cumulus": "rgba(129,199,132,0.13)",
        "cap":     "rgba(120,120,120,0.10)",
        "off":     "rgba(0,0,0,0)",
    }
    regime_bg_colors = [_REGIME_BG.get(h.get("thermal_regime", "off"), "rgba(0,0,0,0)") for h in hrs]
    fig.add_trace(
        go.Bar(
            x=lbl, y=[900] * len(hrs),
            marker=dict(color=regime_bg_colors, line=dict(width=0)),
            hoverinfo="skip", showlegend=False, name="_regime_bg",
        ),
        row=3, col=1,
    )

    def _sw_label(w):
        return ("strong" if w >= 600 else "good" if w >= 400 else
                "moderate" if w >= 150 else "weak")
    def _spread_label(s):
        return ("very dry" if s >= 12 else "dry / good" if s >= 8 else
                "moderate" if s >= 5 else "humid / low cloudbase")
    def _lapse_label(lr):
        return ("strong thermals" if lr >= 22 else "good thermals" if lr >= 18 else
                "moderate" if lr >= 15 else "stable / weak")

    # shortwave radiation — primary y, amber area
    fig.add_trace(
        go.Scatter(
            x=lbl, y=shortwave_vals, name="shortwave (W/m²)",
            fill="tozeroy", fillcolor="rgba(255,213,79,0.30)",
            line=dict(color="#FFD54F", width=1.5),
            mode="lines",
            legend="legend3",
            customdata=[_sw_label(w) for w in shortwave_vals],
            hovertemplate="shortwave: <b>%{y:.0f}</b> W/m²  [%{customdata}]<extra></extra>",
        ),
        row=3, col=1,
    )

    # temp-dewpoint spread — shared right axis (y6, same as lapse rate)
    fig.add_trace(
        go.Scatter(
            x=lbl, y=spread_vals, name="T−Td spread (°C)",
            mode="lines+markers",
            line=dict(color="#80DEEA", width=1.8, dash="dot"),
            marker=dict(size=4, color="#80DEEA"),
            legend="legend3",
            customdata=[[round(s * 125), _spread_label(s)] for s in spread_vals],
            hovertemplate="spread: <b>%{y:.1f}</b> °C  [%{customdata[1]}]  →  cloudbase ≈ %{customdata[0]:.0f} m<extra></extra>",
        ),
        row=3, col=1, secondary_y=True,
    )

    # lapse rate (T2m − T700) — secondary y, orange fill
    fig.add_trace(
        go.Scatter(
            x=lbl, y=lapse_rate_vals, name="T2m−T700 (°C)",
            fill="tozeroy", fillcolor="rgba(255,167,38,0.18)",
            line=dict(color="#FFA726", width=1.8),
            mode="lines",
            legend="legend3",
            customdata=[_lapse_label(lr) for lr in lapse_rate_vals],
            hovertemplate="lapse (gnd–700hPa): <b>%{y:.1f}</b> °C  [%{customdata}]<extra></extra>",
        ),
        row=3, col=1, secondary_y=True,
    )

    # ─────────────────────────────────────────────────────────────────────────
    # ─────────────────────────────────────────────────────────────────────────
    # ROW 4 — atmospheric profile (RH by level · freezing level · inversions)
    # ─────────────────────────────────────────────────────────────────────────

    def _inv_bg(i0: float, i1: float, i2: float) -> str:
        """Background colour based on which inversion layer is present."""
        if i0 > 1:   return "rgba(200,60,40,0.30)"   # surface–925: strong red
        if i1 > 1:   return "rgba(210,120,40,0.24)"  # 925–850: orange
        if i2 > 1:   return "rgba(200,180,50,0.18)"  # 850–700: yellow
        return "rgba(0,0,0,0)"

    inv_bg_colors = [_inv_bg(s, e, h) for s, e, h in zip(inv_sfc_925, inv_925_850, inv_850_700)]
    # hover: summarise inversion state per hour
    def _inv_hover(i0, i1, i2):
        parts = []
        if i0 > 1: parts.append(f"sfc–925 cap: +{i0:.1f}°C @ ~750m")
        if i1 > 1: parts.append(f"925–850 cap: +{i1:.1f}°C @ ~1500m")
        if i2 > 1: parts.append(f"850–700 cap: +{i2:.1f}°C @ ~3000m")
        return " | ".join(parts) if parts else "no inversion"

    inv_hover = [_inv_hover(s, e, h) for s, e, h in zip(inv_sfc_925, inv_925_850, inv_850_700)]
    fig.add_trace(
        go.Bar(
            x=lbl, y=[100] * len(hrs),
            marker=dict(color=inv_bg_colors, line=dict(width=0)),
            customdata=inv_hover, showlegend=False, name="inversion",
            hovertemplate="inversion: <b>%{customdata}</b><extra></extra>",
        ),
        row=4, col=1,
    )

    for name, data, color in [
        ("RH 925 hPa", rh_925_vals, "#4DB6AC"),
        ("RH 850 hPa", rh_850_vals, "#81C784"),
        ("RH 800 hPa", rh_800_vals, "#DCE775"),
        ("RH 700 hPa", rh_700_vals, "#FFB74D"),
    ]:
        fig.add_trace(
            go.Scatter(
                x=lbl, y=data, name=name,
                mode="lines",
                line=dict(color=color, width=1.8),
                legend="legend4",
                hovertemplate=f"{name}: <b>%{{y:.0f}}</b>%<extra></extra>",
            ),
            row=4, col=1,
        )

    # freezing level — secondary y (metres asl)
    fig.add_trace(
        go.Scatter(
            x=lbl, y=fl_vals, name="freezing level (m)",
            mode="lines",
            line=dict(color="#B0BEC5", width=2.0, dash="dash"),
            legend="legend4",
            hovertemplate="freezing level: <b>%{y:.0f} m</b><extra></extra>",
        ),
        row=4, col=1, secondary_y=True,
    )

    # inversion cap lines on altitude axis: horizontal segment at cap altitude,
    # visible only where the inversion is present (None = gap, connectgaps=False)
    for cap_alt, inv_vals, color, cap_name in [
        (750,  inv_sfc_925, "#EF5350", "sfc–925 cap"),
        (1500, inv_925_850, "#FF9800", "925–850 cap"),
        (3000, inv_850_700, "#FDD835", "850–700 cap"),
    ]:
        y_line   = [cap_alt if v > 1 else None for v in inv_vals]
        cust     = [f"{v:+.1f}°C" if v > 1 else None for v in inv_vals]
        fig.add_trace(
            go.Scatter(
                x=lbl, y=y_line, name=cap_name,
                mode="lines+markers",
                line=dict(color=color, width=3.0),
                marker=dict(size=5, color=color),
                connectgaps=False,
                legend="legend4",
                customdata=cust,
                hovertemplate=f"{cap_name}: <b>%{{customdata}}</b><extra></extra>",
            ),
            row=4, col=1, secondary_y=True,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # ROW 6 — foehn pressure gradient
    # ─────────────────────────────────────────────────────────────────────────

    _thresh = site.foehn_delta_p_max_hpa

    fig.add_trace(
        go.Scatter(
            x=lbl, y=dp_vals, name="Δp N−S (hPa)",
            mode="lines",
            line=dict(color="#FFA726", width=2.0),
            fill="tozeroy", fillcolor="rgba(255,167,38,0.15)",
            legend="legend6",
            customdata=[[f"{v:+.0f}", f"{_thresh:.0f}"] for v in dp_vals],
            hovertemplate="Δp (N−S): <b>%{customdata[0]}</b> hPa  (threshold %{customdata[1]})<extra></extra>",
        ),
        row=6, col=1,
    )

    # single positive threshold line, no label
    fig.add_hline(
        y=_thresh, row=6, col=1,
        line=dict(color="#EF5350", dash="dot", width=1.2),
    )

    # ─────────────────────────────────────────────────────────────────────────
    # ROW 7 — wind by level
    # ─────────────────────────────────────────────────────────────────────────

    # gust-range fill polygon (gusts top, wind_10m bottom, reversed)
    fig.add_trace(
        go.Scatter(
            x=lbl + lbl[::-1],
            y=gusts_10m + wind_10m[::-1],
            fill="toself", fillcolor="rgba(41,182,246,0.10)",
            line=dict(color="rgba(0,0,0,0)"),
            hoverinfo="skip", showlegend=False, name="_gustfill",
        ),
        row=7, col=1,
    )

    for name, data, dir_labels, color, dash, width in [
        ("700 hPa",   wind_700,  lbl_700,  "#EF5350", "solid", 2.0),
        ("850 hPa",   wind_850,  lbl_850,  "#FF9800", "solid", 2.0),
        ("925 hPa",   wind_925,  lbl_925,  "#66BB6A", "solid", 2.0),
        ("gusts 10m", gusts_10m, lbl_gust, "#29B6F6", "dot",   1.3),
        ("10m wind",  wind_10m,  lbl_10m,  "#29B6F6", "solid", 1.8),
    ]:
        fig.add_trace(
            go.Scatter(
                x=lbl, y=data, name=name,
                customdata=dir_labels,
                line=dict(color=color, dash=dash, width=width),
                mode="lines",
                legend="legend7",
                hovertemplate=f"{name}: <b>%{{customdata}}</b> km/h<extra></extra>",
            ),
            row=7, col=1,
        )

    for y_val, color, label in [
        (site.launch_wind_max_kmh, "#FF5252", f"launch max {site.launch_wind_max_kmh:.0f}"),
        (site.wind_925_max_kmh,    "#FF8A65", f"925 max {site.wind_925_max_kmh:.0f}"),
    ]:
        fig.add_hline(
            y=y_val, row=7, col=1,
            line=dict(color=color, dash="dot", width=1.5),
            annotation_text=label,
            annotation_font=dict(color=color, size=10),
            annotation_position="top right",
        )

    # ─────────────────────────────────────────────────────────────────────────
    # ROW 5 — cloud cover (stacked) + precip bars (secondary y)
    # ─────────────────────────────────────────────────────────────────────────

    for name, data, fill_color in [
        ("high cloud", cc_high, "rgba(180,200,230,0.50)"),   # pale ice-blue (cirrus)
        ("mid cloud",  cc_mid,  "rgba(80,140,180,0.70)"),    # mid blue (alto)
        ("low cloud",  cc_low,  "rgba(50,60,100,0.90)"),     # dark indigo (stratus)
    ]:
        fig.add_trace(
            go.Scatter(
                x=lbl, y=data, name=name,
                stackgroup="clouds",
                fillcolor=fill_color,
                line=dict(color=fill_color, width=0.3),
                mode="lines",
                legend="legend5",
                hovertemplate=f"{name}: <b>%{{y:.0f}}</b>%<extra></extra>",
            ),
            row=5, col=1,
        )

    fig.add_trace(
        go.Bar(
            x=lbl, y=precip, name="precip (mm/h)",
            marker=dict(color="#64B5F6", opacity=0.85, line=dict(width=0)),
            legend="legend5",
            hovertemplate="precip: <b>%{y:.1f}</b> mm/h<extra></extra>",
        ),
        row=5, col=1, secondary_y=True,
    )


    # ─────────────────────────────────────────────────────────────────────────
    # SUNRISE / SUNSET vertical lines  (span full chart height via yref="paper")
    # ─────────────────────────────────────────────────────────────────────────
    if sun_times and lbl:
        start_hour = int(lbl[0])
        for key, color, ann_pos in [
            ("sunrise",    "#FFD54F", "top left"),
            ("solar_noon", "rgba(255,255,255,0.18)", None),
            ("sunset",     "#FF8A65", "top right"),
        ]:
            dt = sun_times.get(key)
            if dt is None:
                continue
            x_pos = (dt.hour - start_hour) + dt.minute / 60
            if -0.5 <= x_pos <= len(lbl) - 0.5:
                vline_kw = dict(
                    x=x_pos,
                    line=dict(color=color, dash="dot", width=1.2),
                )
                if ann_pos:
                    vline_kw.update(
                        annotation_text=dt.strftime("%H:%M"),
                        annotation_position=ann_pos,
                        annotation_font=dict(size=9, color=color),
                        annotation_bgcolor="rgba(0,0,0,0)",
                        annotation_borderwidth=0,
                    )
                fig.add_vline(**vline_kw)

    # ─────────────────────────────────────────────────────────────────────────
    # GLOBAL LAYOUT
    # ─────────────────────────────────────────────────────────────────────────
    # Per-subplot legend y-positions (paper coords).
    # vertical_spacing=0.08, 6 gaps → plot_area=0.52, each row h=0.07429.
    # Panel tops: row1=1.000, row2=0.846, row3=0.691, row4=0.537, row5=0.383,
    #             row6=0.229, row7=0.074.
    # Legends : yanchor="bottom", y = panel_top + 0.005 → sits just above the panel.
    # Titles  : annotation loop adds +0.040 → mid-gap (half of 0.08 spacing).
    _LEG = dict(orientation="h", xanchor="left", x=0.0,
                bgcolor="rgba(0,0,0,0)", font=dict(size=10), tracegroupgap=4)

    fig.update_layout(
        height=2200,
        paper_bgcolor=BG,
        plot_bgcolor=PANEL_BG,
        font=dict(color=TEXT, size=11, family="system-ui, sans-serif"),
        margin=dict(l=22, r=38, t=68, b=8),
        barmode="group",
        hovermode="x unified",
        hoverlabel=dict(
            bgcolor=PANEL_BG, bordercolor=GRID_C,
            font=dict(size=12, color=TEXT),
            namelength=-1,
        ),
        legend =dict(**_LEG, yanchor="bottom", y=1.005),  # top margin (above row 1)
        legend2=dict(**_LEG, yanchor="bottom", y=0.851),  # gap above row 2
        legend3=dict(**_LEG, yanchor="bottom", y=0.696),  # gap above row 3
        legend4=dict(**_LEG, yanchor="bottom", y=0.542),  # gap above row 4 (atm. profile)
        legend5=dict(**_LEG, yanchor="bottom", y=0.388),  # gap above row 5 (cloud)
        legend6=dict(**_LEG, yanchor="bottom", y=0.234),  # gap above row 6 (foehn)
        legend7=dict(**_LEG, yanchor="bottom", y=0.079),  # gap above row 7 (wind)
    )

    # x-axes: tick labels on every row so the hour is always readable
    for row_i in range(1, 8):
        fig.update_xaxes(
            row=row_i, col=1,
            showgrid=False, linecolor=GRID_C, showline=True,
            tickfont=dict(size=10, color=TEXT),
            showticklabels=True,
            tickangle=0,
        )

    # primary y-axes
    fig.update_yaxes(row=1, col=1, range=[0, 105],  **_axis(nticks=4))
    fig.update_yaxes(row=2, col=1, range=[0, 105],  **_axis(nticks=4))
    fig.update_yaxes(row=3, col=1, range=[0, 900],  **_axis(nticks=4))
    fig.update_yaxes(row=4, col=1, range=[0, 100],  **_axis(nticks=5))   # RH %
    fig.update_yaxes(row=5, col=1, range=[0, 100],  **_axis(nticks=4))   # cloud %
    fig.update_yaxes(row=6, col=1, range=[-12, 12],
                     **_axis(nticks=5, zeroline=True, zerolinecolor=GRID_C, zerolinewidth=1.5))
    fig.update_yaxes(row=7, col=1,                  **_axis(nticks=5))

    # secondary y-axes
    fig.update_yaxes(secondary_y=True, row=2, col=1,
                     range=[0, 100], showgrid=False, nticks=3,
                     tickfont=dict(color="#FFA726", size=8))
    fig.update_yaxes(secondary_y=True, row=3, col=1,
                     range=[0, 30], showgrid=False, nticks=4,
                     tickfont=dict(color="#EF5350", size=8))
    fig.update_yaxes(secondary_y=True, row=4, col=1,     # freezing level (m)
                     range=[0, 5000], showgrid=False, nticks=4,
                     tickfont=dict(color="#B0BEC5", size=8))
    fig.update_yaxes(secondary_y=True, row=5, col=1,     # precip (mm/h)
                     showgrid=False, nticks=3,
                     tickfont=dict(color="#64B5F6", size=8))

    # Subplot title annotations: push upward into mid-gap.
    # make_subplots places them at domain_top (yanchor="bottom"); +0.040 = mid of 0.08 gap.
    for ann in fig.layout.annotations:
        ann.font.size  = 11
        ann.font.color = TEXT
        ann.x          = 0.0
        ann.xanchor    = "left"
        ann.xref       = "paper"
        ann.yanchor    = "bottom"
        ann.y         += 0.040   # lift into gap; row-1 title lands in top margin

    return fig

# ──────────────────────────────────────────────────────────────────────────────
# SIDEBAR
# ──────────────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("🪂 Bombometro")
    st.caption("Paragliding day classifier · Open-Meteo")
    st.divider()

    preset = st.selectbox("📍 Place", list(SITE_PRESETS.keys()))
    p      = SITE_PRESETS[preset]
    model  = st.selectbox("🔮 Model",
                          ["icon_eu", "meteofrance_seamless", "ecmwf_ifs",
                           "meteoswiss_icon_ch1", "italia_meteo_arpae_icon_2i"])
    forecast_days = 5
    fetch_btn     = st.button("🔄 Fetch forecast", type="primary", use_container_width=True)

    st.divider()
    st.caption("ℹ️ Panel guide")

    with st.popover("🚦 Status & fly score", use_container_width=True):
        st.markdown("""
**Coloured bars** — hourly status:
- Green → flyable (gradient by score)
- Red → **wind** veto
- Blue → **precipitation** veto
- Orange → **foehn** veto
- Pink → **gusts** veto
- Grey → **visibility** veto

**Fly score 0–100** (white line): actual score for flyable hours.
**Potential score** (grey dashed): score without any active veto.

*Hover*: veto type + reasons + instant meteo (10m wind, gusts, 925 hPa, precip).
""")

    with st.popover("📊 Component scores", use_container_width=True):
        st.markdown("""
**Per-component bars** (faded = vetoed hour):

| Colour | Component | Evaluates |
|--------|-----------|-----------|
| Blue | Launch | wind direction & speed at launch |
| Green | Upper wind | 925/850/800/700 hPa winds |
| Yellow | Thermal | thermal activity |
| Red | Risk | gusts, rain, snow |

**Foehn** (orange line, right axis 0–100): foehn index — higher = more foehn influence.
Low scores (< 60) in any component reduce the final fly score.
""")

    with st.popover("🌡️ Thermal activity", use_container_width=True):
        st.markdown("""
**Shortwave** (yellow area, left axis W/m²):
Solar radiation driving thermals.
< 150 weak · 150–400 moderate · 400–600 good · > 600 strong

**T−Td spread** (cyan dashed line, right axis °C):
Temperature-dewpoint difference → cloudbase estimate:
`cloudbase ≈ spread × 125 m`

**T2m−T700** (orange area, right axis °C):
Vertical lapse rate from ground to ~3000 m (700hPa):
< 15° stable · 15–18° weak · 18–22° good · > 22° strong

**Background colour**: estimated thermal regime
🔵 blue thermal · 🟢 cumulus · ⬛ cap · transparent off
""")

    with st.popover("🧊 Atmospheric profile", use_container_width=True):
        st.markdown("""
**Relative humidity by level** (left axis, 0–100%):

| Colour | Level | Height |
|--------|-------|--------|
| Teal | 925 hPa | ~750 m |
| Green | 850 hPa | ~1500 m |
| Yellow-green | 800 hPa | ~1950 m |
| Orange | 700 hPa | ~3000 m |

High RH at altitude → risk of early cloudbase, CB development, or blocked thermals.

**Freezing level** (grey dashed, right axis m): altitude of the 0 °C isotherm.
Flying near or above the freezing level = risk of icing and unstable convection.

**Temperature inversions** (right axis, coloured horizontal lines):
An inversion is a layer where temperature *increases* with altitude, capping thermals.

| Colour | Layer | Approx. cap altitude |
|--------|-------|----------------------|
| Red | surface–925 hPa | ~750 m — blocks thermals from launching |
| Orange | 925–850 hPa | ~1500 m — caps low thermals |
| Yellow | 850–700 hPa | ~3000 m — limits thermal height |

**Background shading**: same inversion hierarchy — red = surface cap, orange = elevated, yellow = high.
""")

    with st.popover("☁️ Cloud cover & precip", use_container_width=True):
        st.markdown("""
**Stacked area** (cloud cover %):
- Ice-blue → high cloud / cirrus (> 6000 m)
- Blue → mid cloud / altostratus (2000–6000 m)
- Dark indigo → low cloud / stratus (< 2000 m)

Layers are stacked: total can exceed 100% when all levels are present.

**Blue bars** (right axis): precipitation in mm/h.
""")

    with st.popover("🌬️ Foehn pressure gradient", use_container_width=True):
        st.markdown("""
**Δp N−S** (orange line + fill): pressure difference between the windward (north) and
lee (south) reference stations, in hPa.

- **Positive** → higher pressure north of the Alps → foehn tendency
- **Negative** → higher pressure south → blocking or anti-foehn pattern
- **Red dashed line** → site-specific foehn threshold (`foehn_delta_p_max_hpa`);
  above this value the foehn score reaches its maximum and a veto may apply at 120%

Reference stations are configured per site (e.g. Innsbruck → Bolzano for eastern Alpine
sites, Martigny → Aosta for western Alpine sites).
""")

    with st.popover("💨 Wind by level", use_container_width=True):
        st.markdown("""
Wind speed per pressure level:

| Colour | Level |
|--------|-------|
| Red | 700 hPa (~3000 m) |
| Orange | 850 hPa (~1500 m) |
| Green | 925 hPa (~750 m) |
| Blue solid | 10m wind |
| Blue dashed | 10m gusts |

Dashed horizontal lines = site-specific veto thresholds.
""")

    with st.popover("📐 Pressure levels (AMSL)", use_container_width=True):
        st.markdown("""
Approximate altitude AMSL for each pressure level:

| Level | Altitude |
|-------|----------|
| 10m wind | ~10 m (surface/launch) |
| 925 hPa | ~750 m |
| 850 hPa | ~1500 m |
| 800 hPa | ~1950 m |
| 700 hPa | ~3000 m |

Actual altitudes vary with temperature and surface pressure.

""")

    st.divider()
    st.markdown(
        "<div style='text-align:center;font-size:11px;color:#555'>"
        "Made with ❤️ by "
        "<a href='https://www.giovannispitale.net' target='_blank' "
        "style='color:#64B5F6;text-decoration:none'>Spit</a>"
        "</div>",
        unsafe_allow_html=True,
    )



SITE = SiteConfig(
    name=preset,
    latitude=p["latitude"],               longitude=p["longitude"],
    timezone=p["timezone"],               model=model,
    launch_dir_center_deg=p["launch_dir_center_deg"],
    launch_dir_tolerance_deg=p["launch_dir_tolerance_deg"],
    launch_wind_min_kmh=p["launch_wind_min_kmh"],
    launch_wind_max_kmh=p["launch_wind_max_kmh"],
    gust_max_kmh=p["gust_max_kmh"],
    wind_925_max_kmh=p["wind_925_max_kmh"],
    wind_850_max_kmh=p["wind_850_max_kmh"],
    wind_800_max_kmh=p["wind_800_max_kmh"],
    wind_700_max_kmh=p["wind_700_max_kmh"],
    foehn_delta_p_max_hpa=p["foehn_delta_p_max_hpa"],
    foehn_north_lat=p["foehn_north_lat"],
    foehn_north_lon=p["foehn_north_lon"],
    foehn_south_lat=p["foehn_south_lat"],
    foehn_south_lon=p["foehn_south_lon"],
    foehn_north_name=p.get("foehn_north_name", ""),
    foehn_south_name=p.get("foehn_south_name", ""),
    precip_max_mm=p["precip_max_mm"],     snow_max_cm=p["snow_max_cm"],
    cloud_low_max_pct=p["cloud_low_max_pct"],
    cloud_cover_low_bad=p["cloud_cover_low_bad"],
    cloud_cover_mid_bad=p["cloud_cover_mid_bad"],
    shortwave_good=p["shortwave_good"],
    dewpoint_spread_good=p["dewpoint_spread_good"],
    cape_max=p["cape_max"],
)

# ──────────────────────────────────────────────────────────────────────────────
# CSS
# ──────────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
body, .stApp { background-color: #1C1C2E; color: #E0E0E0; }
div[data-testid="stExpander"] > div { background-color: #252540; }

/* ── Maximise plot area — reduce Streamlit container padding ───────────────── */
.main .block-container {
    padding-left:  0.75rem !important;
    padding-right: 0.75rem !important;
    max-width:     100% !important;
}
@media (max-width: 768px) {
    .main .block-container {
        padding-left:  0.25rem !important;
        padding-right: 0.25rem !important;
    }
}

/* ── Fetch button in sidebar — green ───────────────────────────────────────── */
div[data-testid="stSidebar"] button[data-testid="baseButton-primary"] {
    background-color: #1B5E20 !important;
    border-color:     #2E7D32 !important;
    color:            #FFFFFF !important;
}
div[data-testid="stSidebar"] button[data-testid="baseButton-primary"]:hover {
    background-color: #2E7D32 !important;
    border-color:     #388E3C !important;
}

/* ── Info popover buttons in sidebar — subtle ──────────────────────────────── */
div[data-testid="stSidebar"] button[data-testid="baseButton-secondary"] {
    background:    #252540 !important;
    border:        1px solid rgba(255,255,255,0.12) !important;
    border-radius: 8px !important;
    color:         #90A4AE !important;
    font-size:     11px !important;
    text-align:    left !important;
    padding:       6px 10px !important;
    min-height:    0 !important;
}
div[data-testid="stSidebar"] button[data-testid="baseButton-secondary"]:hover {
    background:    #2c2c4a !important;
    border-color:  rgba(255,255,255,0.25) !important;
    color:         #E0E0E0 !important;
}

/* ── Day-selector card buttons ─────────────────────────────────────────────
   Target only buttons inside the main block (not sidebar).
   We use [data-testid] selectors that Streamlit exposes on its button elements.
*/
div[data-testid="stMainBlockContainer"]
    button[data-testid="baseButton-secondary"] {
    background:    #252540 !important;
    border:        2px solid rgba(255,255,255,0.10) !important;
    border-radius: 16px !important;
    padding:       20px 14px !important;
    width:         100% !important;
    min-height:    140px !important;
    white-space:   pre-line !important;    /* allow \n line breaks */
    text-align:    center !important;
    line-height:   2.0 !important;
    font-size:     12px !important;
    font-weight:   400 !important;
    color:         #9E9E9E !important;
    letter-spacing: 0.3px !important;
    transition:    border-color 0.15s ease, background 0.15s ease !important;
    cursor:        pointer !important;
}
div[data-testid="stMainBlockContainer"]
    button[data-testid="baseButton-secondary"]:hover {
    background:   #2c2c4a !important;
    border-color: rgba(255,255,255,0.25) !important;
    color:        #E0E0E0 !important;
}
/* Selected card → primary type */
div[data-testid="stMainBlockContainer"]
    button[data-testid="baseButton-primary"] {
    background:    #2a2a50 !important;
    border:        2px solid rgba(255,255,255,0.45) !important;
    border-radius: 16px !important;
    padding:       20px 14px !important;
    width:         100% !important;
    min-height:    140px !important;
    white-space:   pre-line !important;
    text-align:    center !important;
    line-height:   2.0 !important;
    font-size:     12px !important;
    font-weight:   400 !important;
    color:         #FFFFFF !important;
    letter-spacing: 0.3px !important;
    cursor:        default !important;
}
</style>
""", unsafe_allow_html=True)

# ──────────────────────────────────────────────────────────────────────────────
# SESSION STATE
# ──────────────────────────────────────────────────────────────────────────────
# Bump this string whenever evaluate_hour logic changes to force cache invalidation
_PIPELINE_VERSION = "v3-component-scores-always"

if st.session_state.get("pipeline_version") != _PIPELINE_VERSION:
    st.session_state.pipeline         = None
    st.session_state.pipeline_version = _PIPELINE_VERSION

# ──────────────────────────────────────────────────────────────────────────────
# FETCH
# ──────────────────────────────────────────────────────────────────────────────
if fetch_btn:
    with st.spinner("Fetching forecast from Open-Meteo…"):
        try:
            fc = _fetch_forecast(SITE.latitude, SITE.longitude,
                                 SITE.timezone, SITE.model, forecast_days)
            ps = _fetch_foehn(SITE.foehn_north_lat, SITE.foehn_north_lon,
                              SITE.foehn_south_lat, SITE.foehn_south_lon,
                              SITE.timezone, forecast_days)
            st.session_state.pipeline = run_pipeline(SITE, forecast_days, fc, ps)
            st.success("Forecast loaded ✓")
        except Exception as e:
            st.error(f"Error: {e}")

if st.session_state.pipeline is None:
    st.info("👈 Configure the site in the sidebar, then click **Fetch forecast**.")
    st.stop()

pipe      = st.session_state.pipeline
evaluated = pipe["evaluated"]
rows      = pipe["rows"]
days      = pipe["available_days"]
summaries = pipe["summaries"]

# ──────────────────────────────────────────────────────────────────────────────
# DAY SELECTOR  — clickable cards, one per forecast day
# ──────────────────────────────────────────────────────────────────────────────
if "selected_day" not in st.session_state or st.session_state.selected_day not in days:
    st.session_state.selected_day = days[0]

cols = st.columns(len(days), gap="small")
for col, d in zip(cols, days):
    sm  = summaries[d]
    vc  = VERDICT_COLORS.get(sm["verdict"], TEXT)
    win = sm.get("best_window")
    is_sel = d == st.session_state.selected_day

    # Multi-line label rendered with white-space:pre-line via CSS
    label = "\n".join([
        d,
        f"{VERDICT_EMOJI.get(sm['verdict'], '')}  {sm['verdict'].upper()}",
        f"[{sm['tag']}]" if sm.get("tag") else "",
        f"fly {sm['mean_fly_score']:.0f}  ·  {sm['usable_hours']}h usable",
        f"{win[0]} – {win[1]}" if win else "no window",
    ])

    with col:
        if is_sel:
            # primary type → selected style (no rerun needed, already selected)
            st.button(label, key=f"card_{d}", type="primary",
                      use_container_width=True, disabled=True)
        else:
            if st.button(label, key=f"card_{d}", type="secondary",
                         use_container_width=True):
                st.session_state.selected_day = d
                st.rerun()

st.markdown("<div style='margin-top:8px'></div>", unsafe_allow_html=True)

# ──────────────────────────────────────────────────────────────────────────────
# DAY DETAIL
# ──────────────────────────────────────────────────────────────────────────────
d  = st.session_state.selected_day
sm = summaries[d]
vc = VERDICT_COLORS.get(sm["verdict"], TEXT)
reasons = sm.get("reasons", [])
tag_str    = f"  [{sm['tag']}]" if sm.get("tag") else ""
reason_str = "  ·  " + "  ·  ".join(reasons) if reasons else ""
st.markdown(
    f"<span style='color:{vc};font-weight:700;font-size:13px;'>"
    f"{sm['verdict'].upper()}{tag_str}</span>"
    f"<span style='color:#9E9E9E;font-size:12px;'>{reason_str}</span>",
    unsafe_allow_html=True,
)

# ── sun times ─────────────────────────────────────────────────────────────────
try:
    _sun = get_sun_times(SITE.latitude, SITE.longitude, SITE.timezone, d)
    st.markdown(
        f"<div style='color:#9E9E9E;font-size:12px;margin:3px 0 6px'>"
        f"🌅&nbsp;<span style='color:#FFD54F'>{_sun['sunrise'].strftime('%H:%M')}</span>"
        f"&emsp;☀️&nbsp;<span style='color:#E0E0E0'>{_sun['solar_noon'].strftime('%H:%M')}</span>"
        f"&emsp;🌆&nbsp;<span style='color:#FF8A65'>{_sun['sunset'].strftime('%H:%M')}</span>"
        f"</div>",
        unsafe_allow_html=True,
    )
except Exception:
    _sun = None

# ──────────────────────────────────────────────────────────────────────────────
# AI ADVISOR
# ──────────────────────────────────────────────────────────────────────────────
_api_key = st.secrets.get("OPENAI_API_KEY", "")

if not st.session_state.get("advisor_unlocked"):
    with st.expander("🤖 AI Advisor", expanded=False):
        st.caption(f"**{SECRET_QUESTION}**")
        col_ans, col_btn = st.columns([4, 1])
        with col_ans:
            ans_input = st.text_input(
                "answer", key="secret_ans",
                label_visibility="collapsed",
                placeholder="your answer…",
            )
        with col_btn:
            if st.button("Unlock", key="unlock_adv", use_container_width=True):
                if check_secret(ans_input):
                    st.session_state.advisor_unlocked = True
                    st.rerun()
                else:
                    st.error("Wrong. Think harder.", icon="🤔")
else:
    _adv_key = f"advisory_{d}_{preset}"

    adv_col, _ = st.columns([1, 5])
    with adv_col:
        ask_btn = st.button("🤖 Ask Bernacca", key=f"ask_marco_{d}",
                            use_container_width=True)

    if ask_btn and _adv_key not in st.session_state:
        if not _api_key:
            st.warning("OpenAI API key not configured (`OPENAI_API_KEY` in Streamlit secrets).")
        else:
            with st.spinner("Bernacca is checking the skies…"):
                ctx = build_day_context(evaluated, rows, SITE, d)
                st.session_state[_adv_key] = _cached_advisory(ctx, _api_key)

    if _adv_key in st.session_state:
        _adv_text   = st.session_state[_adv_key]
        _adv_lines  = _adv_text.strip().split("\n")
        _verdict    = next((l for l in _adv_lines if l.strip().startswith("→")), None)
        _body       = "\n".join(l for l in _adv_lines if not l.strip().startswith("→")).strip()
        _verdict_html = (
            f"<p style='margin:8px 0 0;font-size:14px;font-weight:600;color:#FFA726'>"
            f"{_verdict}</p>"
            if _verdict else ""
        )
        st.markdown(
            f"<div style='background:#1e1e38;border-left:3px solid #FFA726;"
            f"padding:14px 18px;border-radius:8px;margin:6px 0 14px 0'>"
            f"<p style='margin:0;color:#E0E0E0;font-size:13px;line-height:1.65'>{_body}</p>"
            f"{_verdict_html}"
            f"</div>",
            unsafe_allow_html=True,
        )

fig = make_day_chart(d, evaluated, rows, SITE, sun_times=_sun)
if fig:
    st.plotly_chart(fig, use_container_width=True, config={
        "displayModeBar": False,
        "scrollZoom": False,
    })
else:
    st.warning(f"No data for {d}.")

_detail_hrs = [h for h in evaluated
               if h["time"].startswith(d) and 6 <= int(h["time"][11:13]) <= 20]
_detail_rbt  = {r["time"]: r for r in rows}

# ── Expander 1: status + all alerts / reasons ─────────────────────────────────
def _all_reasons(h: dict) -> str:
    parts: list = []
    if h["veto"]:
        parts.extend(h.get("veto_reasons") or [h["veto_type"] or "?"])
        fr = h.get("foehn_reasons") or []
        if fr:
            parts.extend(fr)
    else:
        for key in ("launch_reasons", "upper_wind_reasons",
                    "thermal_reasons", "risk_reasons", "foehn_reasons"):
            parts.extend(h.get(key) or [])
        rpen = _v(h.get("risk_penalty"))
        fpen = _v(h.get("foehn_penalty"))
        fatt = _v(h.get("foehn_attenuation"))
        if rpen > 0: parts.append(f"risk penalty −{rpen:.1f}")
        if fpen > 0: parts.append(f"foehn penalty −{fpen:.1f}")
        if fatt > 0: parts.append(f"foehn attenuated by thermals −{fatt:.1f}")
    return " · ".join(str(p) for p in parts) if parts else ""

def _wlbl(h, key_spd, key_dir) -> str:
    row = _detail_rbt.get(h["time"], {})
    spd = row.get(key_spd)
    drn = row.get(key_dir)
    if spd is None:
        return "—"
    dir_s = f"{wind_dir_label(drn)} " if drn is not None else ""
    return f"{dir_s}{spd:.0f}"

def _wind_cell_color(val: str) -> str:
    try:
        spd = float(str(val).split()[-1])
    except (ValueError, IndexError):
        return ""
    if spd < 15:
        return "background-color: rgba(76,175,80,0.30)"
    if spd < 25:
        return "background-color: rgba(255,235,59,0.30)"
    if spd < 35:
        return "background-color: rgba(255,152,0,0.35)"
    return     "background-color: rgba(244,67,54,0.40)"

with st.expander("💨 Wind by level (dir + km/h)"):
    # 700 hPa on top → 10m at bottom; transpose → levels as rows, hours as columns.
    # Index (level names) is the sticky first column in st.dataframe.
    df_wind = pd.DataFrame(
        {
            "700 hPa": [_wlbl(h, "wind_speed_700hPa", "wind_direction_700hPa") for h in _detail_hrs],
            "800 hPa": [_wlbl(h, "wind_speed_800hPa", "wind_direction_800hPa") for h in _detail_hrs],
            "850 hPa": [_wlbl(h, "wind_speed_850hPa", "wind_direction_850hPa") for h in _detail_hrs],
            "925 hPa": [_wlbl(h, "wind_speed_925hPa", "wind_direction_925hPa") for h in _detail_hrs],
            "gusts":   [f"{_detail_rbt.get(h['time'], {}).get('wind_gusts_10m', 0):.0f}" for h in _detail_hrs],
            "10m":     [_wlbl(h, "wind_speed_10m",    "wind_direction_10m")    for h in _detail_hrs],
        },
        index=[h["time"][11:13] for h in _detail_hrs],
    ).T
    st.dataframe(df_wind.style.map(_wind_cell_color), use_container_width=True)

with st.expander("🔍 Status & alerts"):
    # st.table renders a static HTML table — text wraps naturally, nothing is clipped.
    df_status = pd.DataFrame([{
        "time":    h["time"][11:13],
        "status":  ("✗ " + (h["veto_type"] or "?")) if h["veto"] else "✓",
        "reasons": _all_reasons(h),
    } for h in _detail_hrs])
    st.table(df_status.set_index("time"))
