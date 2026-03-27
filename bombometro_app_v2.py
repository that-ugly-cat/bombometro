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
    run_pipeline,
    wind_dir_label,
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
        precip_max_mm=0,         snow_max_cm=0,
        cloud_low_max_pct=0,     cloud_cover_low_bad=0,
        cloud_cover_mid_bad=0,   shortwave_good=0,
        dewpoint_spread_good=0,  cape_max=0,
    )
    return fetch_forecast(dummy, forecast_days)


@st.cache_data(ttl=1800, show_spinner=False)
def _fetch_foehn(tz, forecast_days):
    return fetch_foehn_pressure_series(tz, forecast_days)

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
    "hammer day":  "🟢",
    "not bad":     "🟡",
    "meh":         "🟠",
    "if you must": "🔴",
    "bad idea":    "⛔",
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
        if rpen > 0:
            parts.append(f"risk penalty −{rpen:.1f}")
        if fpen > 0:
            parts.append(f"foehn penalty −{fpen:.1f}")
    return " · ".join(str(p) for p in parts) if parts else ""

# ──────────────────────────────────────────────────────────────────────────────
# MAIN CHART  — one Plotly figure, 4 subplots, shared x-axis
# ──────────────────────────────────────────────────────────────────────────────

def make_day_chart(day: str, evaluated_all, rows_all, site: SiteConfig):
    """Return a single Plotly figure with 4 vertically-stacked subplots."""
    rbt  = {r["time"]: r for r in rows_all}
    hrs  = [h for h in evaluated_all
            if h["time"].startswith(day) and 6 <= int(h["time"][11:13]) <= 20]
    if not hrs:
        return None

    smry = day_summary(evaluated_all, day)
    lbl  = [h["time"][11:16] for h in hrs]

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
    shortwave_vals  = [_raw(h, rbt, "shortwave_radiation")                           for h in hrs]
    lapse_rate_vals = [_raw(h, rbt, "temperature_2m") - _raw(h, rbt, "temperature_700hPa") for h in hrs]
    spread_vals     = [_raw(h, rbt, "temperature_2m") - _raw(h, rbt, "dew_point_2m")       for h in hrs]

    # ── compass labels ──
    lbl_10m  = [f"{wind_dir_label(d)} {v:.0f}" for d, v in zip(dir_10m,  wind_10m)]
    lbl_925  = [f"{wind_dir_label(d)} {v:.0f}" for d, v in zip(dir_925,  wind_925)]
    lbl_850  = [f"{wind_dir_label(d)} {v:.0f}" for d, v in zip(dir_850,  wind_850)]
    lbl_700  = [f"{wind_dir_label(d)} {v:.0f}" for d, v in zip(dir_700,  wind_700)]
    lbl_gust = [f"{wind_dir_label(d)} {v:.0f}" for d, v in zip(dir_10m,  gusts_10m)]

    # ── figure skeleton ──
    fig = make_subplots(
        rows=5, cols=1,
        shared_xaxes=True,
        row_heights=[0.15, 0.23, 0.18, 0.22, 0.22],
        vertical_spacing=0.04,
        specs=[[{"secondary_y": True}]] * 5,
        subplot_titles=[
            "🚦  Status & fly score",
            "📊  Component scores",
            "🌡️  Thermal activity",
            "💨  Wind by level  (km/h)",
            "☁️  Cloud cover & precipitation",
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

    # rich hover: scores + all reasons grouped by category
    def _rb(label: str, reasons, color: str) -> str:
        """Format one reasons block as HTML (empty string if no reasons)."""
        items = [str(x) for x in (reasons or [])]
        if not items:
            return ""
        return (f"<br><span style='color:{color}'>"
                f"<i>{label}:</i> {' · '.join(items)}</span>")

    hover_txt = []
    for i, h in enumerate(hrs):
        if h["veto"]:
            vr = h.get("veto_reasons") or [h["veto_type"] or "?"]
            top = (f"<b>⛔ {(h['veto_type'] or 'veto').upper()}</b>"
                   f"<br>{' · '.join(str(x) for x in vr)}")
            # foehn reasons always relevant when present
            top += _rb("foehn", h.get("foehn_reasons"), "#FFA726")
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
        "tappo":   "rgba(120,120,120,0.10)",
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
        row=3, col=1,
    )
    fig.data[-1].yaxis = "y6"   # share axis with lapse rate (secondary y row 3)

    # lapse rate (T2m − T700) — secondary y, orange fill
    fig.add_trace(
        go.Scatter(
            x=lbl, y=lapse_rate_vals, name="T2m−T700 (°C)",
            fill="tozeroy", fillcolor="rgba(255,167,38,0.18)",
            line=dict(color="#FFA726", width=1.8),
            mode="lines",
            legend="legend3",
            customdata=[_lapse_label(lr) for lr in lapse_rate_vals],
            hovertemplate="lapse rate: <b>%{y:.1f}</b> °C  [%{customdata}]<extra></extra>",
        ),
        row=3, col=1, secondary_y=True,
    )

    # ─────────────────────────────────────────────────────────────────────────
    # ROW 4 — wind by level
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
        row=4, col=1,
    )

    for name, data, dir_labels, color, dash, width in [
        ("700 hPa",   wind_700,  lbl_700,  "#EF5350", "solid", 2.0),   # red
        ("850 hPa",   wind_850,  lbl_850,  "#FF9800", "solid", 2.0),   # orange
        ("925 hPa",   wind_925,  lbl_925,  "#66BB6A", "solid", 2.0),   # green
        ("gusts 10m", gusts_10m, lbl_gust, "#29B6F6", "dot",   1.3),   # sky blue dotted
        ("10m wind",  wind_10m,  lbl_10m,  "#29B6F6", "solid", 1.8),   # sky blue
    ]:
        fig.add_trace(
            go.Scatter(
                x=lbl, y=data, name=name,
                customdata=dir_labels,
                line=dict(color=color, dash=dash, width=width),
                mode="lines",
                legend="legend4",
                hovertemplate=(
                    f"{name}: <b>%{{customdata}}</b> km/h<extra></extra>"
                ),
            ),
            row=4, col=1,
        )

    for y_val, color, label in [
        (site.launch_wind_max_kmh, "#FF5252", f"launch max {site.launch_wind_max_kmh:.0f}"),
        (site.wind_925_max_kmh,    "#FF8A65", f"925 max {site.wind_925_max_kmh:.0f}"),
    ]:
        fig.add_hline(
            y=y_val, row=4, col=1,
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
    # GLOBAL LAYOUT
    # ─────────────────────────────────────────────────────────────────────────
    # Per-subplot legend y-positions (paper coords).
    # row_heights=[0.15,0.23,0.18,0.22,0.22], spacing=0.04
    # Row 1 top≈0.998, Row 2≈0.832, Row 3≈0.599, Row 4≈0.391, Row 5≈0.166
    # Legends 2-5: yanchor="top", y slightly above each panel top (in spacing).
    # Legend 1: yanchor="bottom", y=1.0 → floats in top margin (t=40).
    _LEG = dict(orientation="h", xanchor="right", x=0.89,
                bgcolor="rgba(0,0,0,0)", font=dict(size=10), tracegroupgap=4)

    fig.update_layout(
        height=1250,
        paper_bgcolor=BG,
        plot_bgcolor=PANEL_BG,
        font=dict(color=TEXT, size=11, family="system-ui, sans-serif"),
        margin=dict(l=55, r=65, t=40, b=20),
        barmode="group",
        hovermode="x unified",
        hoverlabel=dict(
            bgcolor=PANEL_BG, bordercolor=GRID_C,
            font=dict(size=12, color=TEXT),
            namelength=-1,
        ),
        legend =dict(**_LEG, yanchor="bottom", y=1.0),  # row 1: floats in top margin
        legend2=dict(**_LEG, yanchor="top",    y=0.858),   # above row 2 (spacing)
        legend3=dict(**_LEG, yanchor="top",    y=0.622),   # above row 3
        legend4=dict(**_LEG, yanchor="top",    y=0.434),   # above row 4
        legend5=dict(**_LEG, yanchor="top",    y=0.207),   # above row 5
    )

    # x-axes: only show tick labels on the bottom row
    for row_i in range(1, 6):
        fig.update_xaxes(
            row=row_i, col=1,
            showgrid=False, linecolor=GRID_C,
            tickfont=dict(size=10, color=TEXT),
            showticklabels=(row_i == 5),
            tickangle=-45,
        )
    fig.update_xaxes(row=5, col=1, showticklabels=True)

    # primary y-axes
    fig.update_yaxes(row=1, col=1, range=[0, 105],
                     **_axis(title_text="fly score"))
    fig.update_yaxes(row=2, col=1, range=[0, 105],
                     **_axis(title_text="score"))
    fig.update_yaxes(row=3, col=1, range=[0, 900],
                     **_axis(title_text="W/m²"))
    fig.update_yaxes(row=4, col=1,
                     **_axis(title_text="km/h"))
    fig.update_yaxes(row=5, col=1, range=[0, 100],
                     **_axis(title_text="cloud %"))

    # secondary y-axes
    fig.update_yaxes(
        secondary_y=True, row=2, col=1,
        range=[0, 100], showgrid=False,
        title_text="foehn",
        title_font=dict(color="#FFA726", size=10),
        tickfont=dict(color="#FFA726", size=9),
    )
    fig.update_yaxes(
        secondary_y=True, row=3, col=1,
        range=[0, 30], showgrid=False,
        title_text="°C",
        title_font=dict(color="#EF5350", size=10),
        tickfont=dict(color="#EF5350", size=9),
    )
    fig.update_yaxes(
        secondary_y=True, row=5, col=1,
        showgrid=False,
        title_text="precip mm/h",
        title_font=dict(color="#64B5F6", size=10),
        tickfont=dict(color="#64B5F6", size=9),
    )

    # subplot title style (annotations)
    for ann in fig.layout.annotations:
        ann.font.size  = 12
        ann.font.color = TEXT
        ann.x          = 0
        ann.xanchor    = "left"
        ann.xref       = "paper"

    return fig

# ──────────────────────────────────────────────────────────────────────────────
# SIDEBAR
# ──────────────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("🪂 Bombometro")
    st.caption("Paragliding day classifier · Open-Meteo")
    st.divider()

    preset = st.selectbox("Site preset", list(SITE_PRESETS.keys()))
    p      = SITE_PRESETS[preset]

    with st.expander("📍 Location", expanded=(preset == "Custom")):
        site_name = st.text_input("Site name", value=preset)
        lat   = st.number_input("Latitude",  value=p["latitude"],  format="%.4f")
        lon   = st.number_input("Longitude", value=p["longitude"], format="%.4f")
        tz    = st.text_input("Timezone",    value=p["timezone"])
        model = st.selectbox("Model",
                             ["icon_eu", "ecmwf_ifs025", "gfs_seamless", "meteofrance_seamless"])

    with st.expander("🧭 Launch window"):
        dir_center = st.number_input("Dir center (°)",    value=p["launch_dir_center_deg"],    step=5.0)
        dir_tol    = st.number_input("Dir tolerance (°)", value=p["launch_dir_tolerance_deg"], step=5.0)
        wind_min   = st.number_input("Wind min (km/h)",   value=p["launch_wind_min_kmh"],      step=1.0)
        wind_max   = st.number_input("Wind max (km/h)",   value=p["launch_wind_max_kmh"],      step=1.0)
        gust_max   = st.number_input("Gusts max (km/h)",  value=p["gust_max_kmh"],             step=1.0)

    with st.expander("🌬️ Upper winds"):
        w925_max = st.number_input("925 hPa max (km/h)", value=p["wind_925_max_kmh"], step=1.0)
        w850_max = st.number_input("850 hPa max (km/h)", value=p["wind_850_max_kmh"], step=1.0)
        w800_max = st.number_input("800 hPa max (km/h)", value=p["wind_800_max_kmh"], step=1.0)
        w700_max = st.number_input("700 hPa max (km/h)", value=p["wind_700_max_kmh"], step=1.0)

    with st.expander("🌧️ Precip & clouds"):
        precip_max   = st.number_input("Precip max (mm/h)", value=p["precip_max_mm"],    step=0.05, format="%.2f")
        snow_max     = st.number_input("Snow max (cm)",     value=p["snow_max_cm"],       step=0.05, format="%.2f")
        cloud_lo_max = st.number_input("Low cloud max (%)", value=p["cloud_low_max_pct"], step=1.0)

    with st.expander("🌡️ Foehn"):
        foehn_dp = st.number_input("Foehn ΔP max (hPa)", value=p["foehn_delta_p_max_hpa"], step=0.5)

    forecast_days = st.slider("Forecast days", 1, 7, 2)
    fetch_btn     = st.button("🔄 Fetch forecast", type="primary", use_container_width=True)

SITE = SiteConfig(
    name=site_name, latitude=lat, longitude=lon, timezone=tz, model=model,
    launch_dir_center_deg=dir_center, launch_dir_tolerance_deg=dir_tol,
    launch_wind_min_kmh=wind_min,     launch_wind_max_kmh=wind_max,
    gust_max_kmh=gust_max,            wind_925_max_kmh=w925_max,
    wind_850_max_kmh=w850_max,        wind_800_max_kmh=w800_max,
    wind_700_max_kmh=w700_max,        foehn_delta_p_max_hpa=foehn_dp,
    precip_max_mm=precip_max,         snow_max_cm=snow_max,
    cloud_low_max_pct=cloud_lo_max,
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
            ps = _fetch_foehn(SITE.timezone, forecast_days)
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

fig = make_day_chart(d, evaluated, rows, SITE)
if fig:
    st.plotly_chart(fig, use_container_width=True, config={
        "displayModeBar": True,
        "modeBarButtonsToRemove": ["select2d", "lasso2d", "autoScale2d"],
        "displaylogo": False,
        "scrollZoom": False,
    })
else:
    st.warning(f"No data for {d}.")

with st.expander("🔍 Hour-by-hour detail"):
    day_hrs = [h for h in evaluated
               if h["time"].startswith(d) and 6 <= int(h["time"][11:13]) <= 20]
    df = pd.DataFrame([{
        "time":       h["time"][11:16],
        "status":     ("✗ " + (h["veto_type"] or "?")) if h["veto"] else "✓",
        "fly":        _v(h["fly_score"]),
        "potential":  _v(h["potential_score"]),
        "launch":     _v(h["launch_score"]),
        "upper wind": _v(h["upper_wind_score"]),
        "thermal":    _v(h["thermal_score"]),
        "risk":       _v(h["risk_score"]),
        "foehn":      _v(h["foehn_score"]),
        "cloudbase":  int(h["cloudbase_estimate_m"]) if h["cloudbase_estimate_m"] else "",
        "regime":     h["thermal_regime"] or "",
        "alerts":     _alerts_str(h),
    } for h in day_hrs])
    st.dataframe(df, use_container_width=True, hide_index=True)
