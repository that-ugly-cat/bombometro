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
    fly_sc     = [_v(h["fly_score"])        for h in hrs]
    launch_sc  = [_v(h["launch_score"])     for h in hrs]
    upper_sc   = [_v(h["upper_wind_score"]) for h in hrs]
    thermal_sc = [_v(h["thermal_score"])    for h in hrs]
    risk_sc    = [_v(h["risk_score"])       for h in hrs]
    foehn_sc   = [_v(h["foehn_score"])      for h in hrs]
    cloudbase  = [h["cloudbase_estimate_m"] for h in hrs]

    # ── raw meteo ──
    wind_10m  = [_raw(h, rbt, "wind_speed_10m")    for h in hrs]
    gusts_10m = [_raw(h, rbt, "wind_gusts_10m")    for h in hrs]
    wind_925  = [_raw(h, rbt, "wind_speed_925hPa") for h in hrs]
    wind_850  = [_raw(h, rbt, "wind_speed_850hPa") for h in hrs]
    wind_700  = [_raw(h, rbt, "wind_speed_700hPa") for h in hrs]
    precip    = [_raw(h, rbt, "precipitation")     for h in hrs]
    cc_low    = [_raw(h, rbt, "cloud_cover_low")   for h in hrs]
    cc_mid    = [_raw(h, rbt, "cloud_cover_mid")   for h in hrs]
    cc_high   = [_raw(h, rbt, "cloud_cover_high")  for h in hrs]

    # ── figure skeleton ──
    fig = make_subplots(
        rows=4, cols=1,
        shared_xaxes=True,
        row_heights=[0.20, 0.30, 0.25, 0.25],
        vertical_spacing=0.06,
        specs=[[{"secondary_y": True}]] * 4,
        subplot_titles=[
            "🚦  Status & fly score",
            "📊  Component scores",
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

    # rich hover: all meteo packed into each bar
    hover_txt = []
    for i, h in enumerate(hrs):
        if h["veto"]:
            rv  = " · ".join(h.get("veto_reasons", [h["veto_type"] or "?"]))
            top = f"<b>⛔ {(h['veto_type'] or 'veto').upper()}</b><br>{rv}"
        else:
            top = (
                f"<b>fly {_v(h['fly_score']):.0f}</b>"
                f"  launch {_v(h['launch_score']):.0f}"
                f"  UW {_v(h['upper_wind_score']):.0f}"
                f"  thermal {_v(h['thermal_score']):.0f}"
                f"  risk {_v(h['risk_score']):.0f}"
            )
            if cloudbase[i] is not None:
                top += f"<br>cloudbase ≈ {int(cloudbase[i])} m  [{h.get('thermal_regime','')}]"
        met = (
            f"<br><span style='color:#9E9E9E'>"
            f"G {gusts_10m[i]:.0f} km/h  "
            f"925 {wind_925[i]:.0f} km/h  "
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

    # fly-score line (non-vetoed only)
    fly_x = [lbl[i] for i, h in enumerate(hrs) if not h["veto"] and _v(h["fly_score"]) > 0]
    fly_y = [_v(h["fly_score"]) for h in hrs    if not h["veto"] and _v(h["fly_score"]) > 0]
    if fly_x:
        fig.add_trace(
            go.Scatter(
                x=fly_x, y=fly_y, name="fly score",
                mode="lines+markers",
                line=dict(color="white", width=2.5),
                marker=dict(size=7, color="white", line=dict(color=PANEL_BG, width=1.5)),
                hovertemplate="fly score: <b>%{y:.0f}</b><extra></extra>",
            ),
            row=1, col=1,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # ROW 2 — fly-score area + component bars + foehn line (secondary y)
    # ─────────────────────────────────────────────────────────────────────────

    # fly score fill (background reference)
    fig.add_trace(
        go.Scatter(
            x=lbl, y=fly_sc,
            fill="tozeroy", fillcolor="rgba(255,255,255,0.06)",
            line=dict(color="white", width=2.5),
            mode="lines+markers",
            marker=dict(size=5, color="white", line=dict(color=PANEL_BG, width=1)),
            name="fly score", showlegend=False,
            hovertemplate="fly score: <b>%{y:.0f}</b><extra></extra>",
        ),
        row=2, col=1,
    )

    for name, data, color in [
        ("launch",     launch_sc,  "#4FC3F7"),
        ("upper wind", upper_sc,   "#81C784"),
        ("thermal",    thermal_sc, "#FFD54F"),
        ("risk",       risk_sc,    "#EF9A9A"),
    ]:
        fig.add_trace(
            go.Bar(
                x=lbl, y=data, name=name,
                marker=dict(color=color, line=dict(width=0)),
                opacity=0.82,
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
            hovertemplate="foehn: <b>%{y:.0f}</b><extra></extra>",
        ),
        row=2, col=1, secondary_y=True,
    )

    # ─────────────────────────────────────────────────────────────────────────
    # ROW 3 — wind by level
    # ─────────────────────────────────────────────────────────────────────────

    # gust-range fill polygon (gusts top, wind_10m bottom, reversed)
    fig.add_trace(
        go.Scatter(
            x=lbl + lbl[::-1],
            y=gusts_10m + wind_10m[::-1],
            fill="toself", fillcolor="rgba(128,222,234,0.12)",
            line=dict(color="rgba(0,0,0,0)"),
            hoverinfo="skip", showlegend=False, name="_gustfill",
        ),
        row=3, col=1,
    )

    for name, data, color, dash, width in [
        ("10m wind",  wind_10m,  "#80DEEA", "solid", 1.8),
        ("gusts 10m", gusts_10m, "#80DEEA", "dot",   1.3),
        ("925 hPa",   wind_925,  "#4FC3F7", "solid", 2.0),
        ("850 hPa",   wind_850,  "#7986CB", "solid", 2.0),
        ("700 hPa",   wind_700,  "#CE93D8", "solid", 2.0),
    ]:
        fig.add_trace(
            go.Scatter(
                x=lbl, y=data, name=name,
                line=dict(color=color, dash=dash, width=width),
                mode="lines",
                hovertemplate=f"{name}: <b>%{{y:.0f}}</b> km/h<extra></extra>",
            ),
            row=3, col=1,
        )

    for y_val, color, label in [
        (site.launch_wind_max_kmh, "#FF5252", f"launch max {site.launch_wind_max_kmh:.0f}"),
        (site.wind_925_max_kmh,    "#FF8A65", f"925 max {site.wind_925_max_kmh:.0f}"),
    ]:
        fig.add_hline(
            y=y_val, row=3, col=1,
            line=dict(color=color, dash="dot", width=1.5),
            annotation_text=label,
            annotation_font=dict(color=color, size=10),
            annotation_position="top right",
        )

    # ─────────────────────────────────────────────────────────────────────────
    # ROW 4 — cloud cover (stacked) + precip bars (secondary y)
    # ─────────────────────────────────────────────────────────────────────────

    for name, data, fill_color in [
        ("high cloud", cc_high, "rgba(69,90,100,0.80)"),
        ("mid cloud",  cc_mid,  "rgba(84,110,122,0.80)"),
        ("low cloud",  cc_low,  "rgba(96,125,139,0.80)"),
    ]:
        fig.add_trace(
            go.Scatter(
                x=lbl, y=data, name=name,
                stackgroup="clouds",
                fillcolor=fill_color,
                line=dict(color=fill_color, width=0.3),
                mode="lines",
                hovertemplate=f"{name}: <b>%{{y:.0f}}</b>%<extra></extra>",
            ),
            row=4, col=1,
        )

    fig.add_trace(
        go.Bar(
            x=lbl, y=precip, name="precip (mm/h)",
            marker=dict(color="#64B5F6", opacity=0.85, line=dict(width=0)),
            hovertemplate="precip: <b>%{y:.1f}</b> mm/h<extra></extra>",
        ),
        row=4, col=1, secondary_y=True,
    )

    # ─────────────────────────────────────────────────────────────────────────
    # GLOBAL LAYOUT
    # ─────────────────────────────────────────────────────────────────────────
    verdict  = smry.get("verdict", "?")
    tag      = smry.get("tag", "")
    win      = smry.get("best_window")
    mean_fly = smry.get("mean_fly_score", 0)
    win_str  = f"  ·  best {win[0]}–{win[1]}" if win else "  ·  no window"

    fig.update_layout(
        height=1050,
        paper_bgcolor=BG,
        plot_bgcolor=PANEL_BG,
        font=dict(color=TEXT, size=11, family="system-ui, sans-serif"),
        margin=dict(l=55, r=70, t=90, b=20),
        title=dict(
            text=f"<b>{site.name}</b>   {day}   <b>{verdict.upper()}</b>   [{tag}]   fly {mean_fly:.0f}{win_str}",
            font=dict(size=13, color=TEXT),
            x=0, xanchor="left",
        ),
        barmode="group",
        hovermode="x unified",
        hoverlabel=dict(
            bgcolor=PANEL_BG, bordercolor=GRID_C,
            font=dict(size=12, color=TEXT),
            namelength=-1,
        ),
        legend=dict(
            orientation="h", yanchor="bottom", y=1.02,
            xanchor="right", x=1,
            bgcolor="rgba(0,0,0,0)", font=dict(size=10),
            traceorder="normal",
        ),
    )

    # x-axes: only show tick labels on the bottom row
    for row_i in range(1, 5):
        fig.update_xaxes(
            row=row_i, col=1,
            showgrid=False, linecolor=GRID_C,
            tickfont=dict(size=10, color=TEXT),
            showticklabels=(row_i == 4),
            tickangle=-45,
        )
    fig.update_xaxes(row=4, col=1, showticklabels=True)

    # primary y-axes
    fig.update_yaxes(row=1, col=1, range=[0, 105],
                     **_axis(title_text="fly score"))
    fig.update_yaxes(row=2, col=1, range=[0, 105],
                     **_axis(title_text="score"))
    fig.update_yaxes(row=3, col=1,
                     **_axis(title_text="km/h"))
    fig.update_yaxes(row=4, col=1, range=[0, 100],
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
        secondary_y=True, row=4, col=1,
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
.stTabs [data-baseweb="tab-list"]  { gap: 8px; }
.stTabs [data-baseweb="tab"]       { background-color: #252540; border-radius: 6px;
                                      padding: 6px 18px; color: #E0E0E0; }
.stTabs [aria-selected="true"]     { background-color: #383860 !important; }
div[data-testid="stExpander"] > div { background-color: #252540; }
</style>
""", unsafe_allow_html=True)

# ──────────────────────────────────────────────────────────────────────────────
# SESSION STATE
# ──────────────────────────────────────────────────────────────────────────────
if "pipeline" not in st.session_state:
    st.session_state.pipeline = None

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
# SUMMARY CARDS
# ──────────────────────────────────────────────────────────────────────────────
cols = st.columns(len(days))
for col, d in zip(cols, days):
    sm = summaries[d]
    vc = VERDICT_COLORS.get(sm["verdict"], TEXT)
    col.markdown(
        f"""<div style="background:#252540;border-radius:10px;padding:14px 10px;text-align:center;">
        <div style="font-size:11px;color:#9E9E9E;">{d}</div>
        <div style="font-size:22px;font-weight:bold;color:{vc};">{sm['verdict'].upper()}</div>
        <div style="font-size:12px;color:#FFA726;">[{sm['tag']}]</div>
        <div style="font-size:11px;color:#E0E0E0;margin-top:4px;">
          fly {sm['mean_fly_score']:.0f} · {sm['usable_hours']} h usable
        </div></div>""",
        unsafe_allow_html=True,
    )

st.markdown("<br>", unsafe_allow_html=True)

# ──────────────────────────────────────────────────────────────────────────────
# PER-DAY TABS
# ──────────────────────────────────────────────────────────────────────────────
tabs = st.tabs([f"📅 {d}" for d in days])
for tab, d in zip(tabs, days):
    with tab:
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
                "launch":     _v(h["launch_score"]),
                "upper wind": _v(h["upper_wind_score"]),
                "thermal":    _v(h["thermal_score"]),
                "risk":       _v(h["risk_score"]),
                "foehn":      _v(h["foehn_score"]),
                "cloudbase":  int(h["cloudbase_estimate_m"]) if h["cloudbase_estimate_m"] else "",
                "regime":     h["thermal_regime"] or "",
            } for h in day_hrs])
            st.dataframe(df, use_container_width=True, hide_index=True)
