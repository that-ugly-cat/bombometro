"""
bombometro · app.py
===================
Streamlit Cloud frontend.
All domain logic lives in core.py — this file only handles UI and charts.
"""

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import streamlit as st
from matplotlib.gridspec import GridSpec

from core import (
    SiteConfig, SITE_PRESETS,
    fetch_forecast, fetch_foehn_pressure_series,
    run_pipeline, day_summary,
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
def cached_fetch_forecast(lat, lon, tz, model, forecast_days):
    from core import SiteConfig, fetch_forecast, HOURLY_VARS
    # build a minimal SiteConfig just for the fetch
    _dummy = SiteConfig(
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
    return fetch_forecast(_dummy, forecast_days)


@st.cache_data(ttl=1800, show_spinner=False)
def cached_fetch_foehn(tz, forecast_days):
    return fetch_foehn_pressure_series(tz, forecast_days)

# ──────────────────────────────────────────────────────────────────────────────
# PALETTE & VIZ CONSTANTS
# ──────────────────────────────────────────────────────────────────────────────

VETO_COLORS = {
    "wind":          "#EF5350",
    "precipitation": "#42A5F5",
    "foehn":         "#FFA726",
    "visibility":    "#78909C",
    "gusts":         "#EC407A",
    None:            "#66BB6A",
}
SCORE_COLORS = {
    "launch":     "#4FC3F7",
    "upper_wind": "#81C784",
    "thermal":    "#FFD54F",
    "risk":       "#EF9A9A",
    "foehn_line": "#FFA726",
}
VERDICT_COLORS = {
    "hammer day": "#69F0AE",
    "not bad":    "#AED581",
    "meh":        "#FFD740",
    "if you must":"#FFAB40",
    "bad idea":   "#FF5252",
}
FLY_CMAP          = plt.cm.RdYlGn
BG, PANEL_BG      = "#1C1C2E", "#252540"
TEXT, GRID_C      = "#E0E0E0", "#383860"


def _v(val, default=0.0):
    return val if val is not None else default


def _raw(row, rbt, key, default=0.0):
    return _v(rbt.get(row["time"], {}).get(key), default)


def _style(ax, x, labels):
    ax.set_facecolor(PANEL_BG)
    ax.tick_params(colors=TEXT, labelsize=8)
    ax.xaxis.label.set_color(TEXT)
    ax.yaxis.label.set_color(TEXT)
    for sp in ax.spines.values():
        sp.set_color(GRID_C)
    ax.grid(axis="y", color=GRID_C, linewidth=0.5, linestyle="--", zorder=0)
    ax.set_xlim(-0.5, len(x) - 0.5)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=7)


def _style_twin(ax):
    ax.set_facecolor(PANEL_BG)
    ax.tick_params(labelsize=7)
    for sp in ax.spines.values():
        sp.set_color(GRID_C)

# ──────────────────────────────────────────────────────────────────────────────
# CHART  (one figure per day)
# ──────────────────────────────────────────────────────────────────────────────

def make_flight_fig(day, evaluated_all, rows_all, site):
    rbt = {r["time"]: r for r in rows_all}
    hrs = [h for h in evaluated_all
           if h["time"].startswith(day) and 6 <= int(h["time"][11:13]) <= 20]
    if not hrs:
        return None

    smry   = day_summary(evaluated_all, day)
    labels = [h["time"][11:16] for h in hrs]
    x      = np.arange(len(hrs))

    # score series
    fly_sc     = [_v(h["fly_score"])        for h in hrs]
    launch_sc  = [_v(h["launch_score"])     for h in hrs]
    upper_sc   = [_v(h["upper_wind_score"]) for h in hrs]
    thermal_sc = [_v(h["thermal_score"])    for h in hrs]
    risk_sc    = [_v(h["risk_score"])       for h in hrs]
    foehn_sc   = [_v(h["foehn_score"])      for h in hrs]
    cloudbase  = [h["cloudbase_estimate_m"] for h in hrs]

    # raw meteo series
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
    for ax in axes:
        _style(ax, x, labels)

    # ── header ────────────────────────────────────────────────────────────────
    verdict  = smry.get("verdict", "?")
    tag      = smry.get("tag", "")
    win      = smry.get("best_window")
    cb_m     = smry.get("typical_cloudbase_m")
    mean_fly = smry.get("mean_fly_score", 0)
    mean_foe = smry.get("mean_foehn_score", 0)
    mean_rsk = smry.get("mean_risk_score", 0)
    usable_h = smry.get("usable_hours", 0)
    vcol     = VERDICT_COLORS.get(verdict, TEXT)
    win_str  = f"  ·  best window: {win[0]}–{win[1]}" if win else "  ·  no usable window"
    cb_str   = f"  ·  cloudbase ≈ {int(cb_m)} m"      if cb_m else ""

    fig.text(0.01, 0.955, f"{site.name}  —  {day}",
             fontsize=11, color=TEXT, fontweight="bold", va="top")
    fig.text(0.01, 0.925, verdict.upper(),
             fontsize=24, color=vcol, fontweight="bold", va="top")
    if tag:
        fig.text(0.22, 0.930, f"[{tag}]",
                 fontsize=12, color="#FFA726", fontweight="bold", va="top")
    fig.text(0.37, 0.932,
             f"fly {mean_fly:.0f}  ·  foehn {mean_foe:.0f}  ·  risk {mean_rsk:.0f}"
             f"  ·  usable h: {usable_h}{win_str}{cb_str}",
             fontsize=9, color=TEXT, va="top")
    reasons = smry.get("reasons", [])
    if reasons:
        fig.text(0.37, 0.910, "  ·  ".join(reasons),
                 fontsize=7.5, color="#9E9E9E", va="top")

    # ── P1: status strip + fly-score line, annotated ─────────────────────────
    ax1 = axes[0]
    bar_colors = [
        VETO_COLORS.get(h["veto_type"], "#888") if h["veto"]
        else FLY_CMAP(_v(h["fly_score"]) / 100.0)
        for h in hrs
    ]
    ax1.bar(x, [100] * len(x), color=bar_colors, width=0.85, alpha=0.90, zorder=2)

    for i, h in enumerate(hrs):
        lines = [f"G {gusts_10m[i]:.0f}", f"925 {wind_925[i]:.0f}"]
        if precip[i] > 0.05:
            lines.append(f"P {precip[i]:.1f}")
        ax1.text(i, 97, "\n".join(lines), ha="center", va="top",
                 fontsize=5.5, color="white", alpha=0.85,
                 linespacing=1.4, fontfamily="monospace", zorder=4)

    fx = [i for i, h in enumerate(hrs) if not h["veto"] and _v(h["fly_score"]) > 0]
    fs = [_v(h["fly_score"]) for h in hrs if not h["veto"] and _v(h["fly_score"]) > 0]
    if fx:
        ax1.plot(fx, fs, "o-", color="white", lw=1.5, ms=5, alpha=0.9, zorder=5, label="fly score")

    ax1.set_ylim(0, 105)
    ax1.set_ylabel("fly score", fontsize=8)
    ax1.set_title("Status & fly score", color=TEXT, fontsize=9, pad=5, loc="left")
    ax1.legend(
        handles=[mpatches.Patch(color=c, label=lbl or "flyable") for lbl, c in VETO_COLORS.items()],
        loc="upper right", fontsize=7, ncol=3,
        facecolor=PANEL_BG, labelcolor=TEXT, edgecolor=GRID_C,
    )

    # ── P2: fly score area + component score bars ─────────────────────────────
    ax2 = axes[1]
    ax2.fill_between(x, 0, fly_sc, color="white", alpha=0.08, zorder=1)
    ax2.plot(x, fly_sc, color="white", lw=2.5, alpha=0.85, zorder=5,
             label="fly score", marker="o", ms=4)
    w = 0.20
    ax2.bar(x - 1.5*w, launch_sc,  width=w, label="launch",     color=SCORE_COLORS["launch"],     alpha=0.80, zorder=3)
    ax2.bar(x - 0.5*w, upper_sc,   width=w, label="upper wind", color=SCORE_COLORS["upper_wind"], alpha=0.80, zorder=3)
    ax2.bar(x + 0.5*w, thermal_sc, width=w, label="thermal",    color=SCORE_COLORS["thermal"],    alpha=0.80, zorder=3)
    ax2.bar(x + 1.5*w, risk_sc,    width=w, label="risk",       color=SCORE_COLORS["risk"],       alpha=0.80, zorder=3)
    ax2r = ax2.twinx()
    _style_twin(ax2r)
    ax2r.plot(x, foehn_sc, color=SCORE_COLORS["foehn_line"], lw=1.8,
              linestyle="--", marker="D", ms=3, label="foehn", zorder=4)
    ax2r.set_ylim(0, 100)
    ax2r.tick_params(colors="#FFA726", labelsize=7)
    ax2r.set_ylabel("foehn score", color="#FFA726", fontsize=7)
    ax2.set_ylim(0, 100)
    ax2.set_ylabel("score", fontsize=8)
    ax2.set_title("Fly score & component scores", color=TEXT, fontsize=9, pad=5, loc="left")
    hl, ll = ax2.get_legend_handles_labels()
    hr, lr = ax2r.get_legend_handles_labels()
    ax2.legend(hl + hr, ll + lr, loc="upper left", fontsize=7, ncol=6,
               facecolor=PANEL_BG, labelcolor=TEXT, edgecolor=GRID_C)

    # ── P3: wind by level ─────────────────────────────────────────────────────
    ax3 = axes[2]
    ax3.fill_between(x, wind_10m, gusts_10m, alpha=0.15, color="#80DEEA", label="gust range", zorder=1)
    ax3.plot(x, wind_10m,  color="#80DEEA", lw=1.8, label="10m",      marker="o", ms=3, zorder=3)
    ax3.plot(x, gusts_10m, color="#80DEEA", lw=1.0, linestyle=":",    label="gusts 10m",    zorder=3)
    ax3.plot(x, wind_925,  color="#4FC3F7", lw=1.8, label="925 hPa",  zorder=3)
    ax3.plot(x, wind_850,  color="#7986CB", lw=1.8, label="850 hPa",  zorder=3)
    ax3.plot(x, wind_700,  color="#CE93D8", lw=1.8, label="700 hPa",  zorder=3)
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
                  labels=["cloud high", "cloud mid", "cloud low"],
                  colors=["#455A64", "#546E7A", "#607D8B"], alpha=0.75, zorder=1)
    ax4.set_ylim(0, 100)
    ax4.set_ylabel("cloud cover %", fontsize=8)
    ax4.set_title("Cloud cover, precipitation & cloudbase", color=TEXT, fontsize=9, pad=5, loc="left")

    ax4r = ax4.twinx()
    _style_twin(ax4r)
    ax4r.bar(x, precip, color="#64B5F6", alpha=0.75, width=0.5, label="precip (mm/h)", zorder=3)
    ax4r.tick_params(colors="#64B5F6", labelsize=7)
    ax4r.set_ylabel("precip (mm/h)", color="#64B5F6", fontsize=7)

    ax4b = ax4.twinx()
    ax4b.spines["right"].set_position(("axes", 1.07))
    _style_twin(ax4b)
    cb_clean = [c if c is not None else float("nan") for c in cloudbase]
    ax4b.plot(x, cb_clean, color="#FFCC02", lw=1.8, linestyle="-.",
              marker="s", ms=3, label="cloudbase (m)", zorder=4)
    ax4b.tick_params(colors="#FFCC02", labelsize=7)
    ax4b.set_ylabel("cloudbase (m)", color="#FFCC02", fontsize=7)

    h4,  l4  = ax4.get_legend_handles_labels()
    h4r, l4r = ax4r.get_legend_handles_labels()
    h4b, l4b = ax4b.get_legend_handles_labels()
    ax4.legend(h4 + h4r + h4b, l4 + l4r + l4b, loc="upper right", fontsize=7, ncol=3,
               facecolor=PANEL_BG, labelcolor=TEXT, edgecolor=GRID_C)

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
        precip_max   = st.number_input("Precip max (mm/h)", value=p["precip_max_mm"],      step=0.05, format="%.2f")
        snow_max     = st.number_input("Snow max (cm)",     value=p["snow_max_cm"],         step=0.05, format="%.2f")
        cloud_lo_max = st.number_input("Low cloud max (%)", value=p["cloud_low_max_pct"],   step=1.0)

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
# DARK-THEME CSS
# ──────────────────────────────────────────────────────────────────────────────

st.markdown("""
<style>
body, .stApp { background-color: #1C1C2E; color: #E0E0E0; }
.stTabs [data-baseweb="tab-list"] { gap: 8px; }
.stTabs [data-baseweb="tab"]      { background-color: #252540; border-radius: 6px;
                                     padding: 6px 18px; color: #E0E0E0; }
.stTabs [aria-selected="true"]    { background-color: #383860 !important; }
</style>
""", unsafe_allow_html=True)

# ──────────────────────────────────────────────────────────────────────────────
# SESSION STATE
# ──────────────────────────────────────────────────────────────────────────────

if "pipeline" not in st.session_state:
    st.session_state.pipeline = None

# ──────────────────────────────────────────────────────────────────────────────
# FETCH  (triggered by button)
# ──────────────────────────────────────────────────────────────────────────────

if fetch_btn:
    with st.spinner("Fetching forecast from Open-Meteo…"):
        try:
            fc = cached_fetch_forecast(SITE.latitude, SITE.longitude,
                                       SITE.timezone, SITE.model, forecast_days)
            ps = cached_fetch_foehn(SITE.timezone, forecast_days)
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
# SUMMARY CARDS  (one per day)
# ──────────────────────────────────────────────────────────────────────────────

cols = st.columns(len(days))
for col, d in zip(cols, days):
    sm  = summaries[d]
    vc  = VERDICT_COLORS.get(sm["verdict"], TEXT)
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
        fig = make_flight_fig(d, evaluated, rows, SITE)
        if fig:
            st.pyplot(fig, use_container_width=True)
            plt.close(fig)
        else:
            st.warning(f"No data for {d}")

        with st.expander("🔍 Hour-by-hour detail"):
            day_hrs = [h for h in evaluated
                       if h["time"].startswith(d) and 6 <= int(h["time"][11:13]) <= 20]
            df = pd.DataFrame([{
                "time":       h["time"][11:16],
                "veto":       "✗ " + h["veto_type"] if h["veto"] else "✓",
                "fly":        _v(h["fly_score"]),
                "launch":     _v(h["launch_score"]),
                "upper_wind": _v(h["upper_wind_score"]),
                "thermal":    _v(h["thermal_score"]),
                "risk":       _v(h["risk_score"]),
                "foehn":      _v(h["foehn_score"]),
                "cloudbase":  h["cloudbase_estimate_m"] or "",
                "regime":     h["thermal_regime"] or "",
            } for h in day_hrs])
            st.dataframe(df, use_container_width=True, hide_index=True)
