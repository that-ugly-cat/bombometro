"""
bombometro · advisor.py
=======================
AI-powered day advisory — GPT-4o-mini.
Persona: Bernacca, senior paragliding instructor + mountain meteorologist.
"""

from __future__ import annotations

from typing import Any, Dict, List

# ─────────────────────────────────────────────────────────────────────────────
# SECRET GATE
# ─────────────────────────────────────────────────────────────────────────────

SECRET_QUESTION = 'Complete the sentence: "I have never thrown my reserve—"'
_SECRET_ANSWER  = "yet"


def check_secret(user_input: str) -> bool:
    """Return True if the user's answer matches the secret passphrase."""
    return user_input.strip().lower() == _SECRET_ANSWER


# ─────────────────────────────────────────────────────────────────────────────
# PERSONA
# ─────────────────────────────────────────────────────────────────────────────

_SYSTEM = """\
You are Bernacca, a senior paragliding instructor and certified mountain meteorologist \
with 25 years of experience on Alpine and pre-Alpine flying sites. \
Your style is direct and pragmatic — you call things as they are, never sugarcoat \
a bad day, but get genuinely excited about a good one. \
You use meteorological and paragliding jargon correctly, and briefly explain \
a term only when it genuinely adds value for the reader.

You are given hourly forecast data and computed scoring metrics for a specific \
flying site and day. Write a SHORT advisory (80–120 words) that:
1. Describes the overall character of the day (thermic, foehn-influenced, blocked, mixed…)
2. Identifies the best flying window, or explains clearly why there isn't one
3. Names the main risk or limiting factor
4. Ends with a single punchy verdict sentence on its own line, prefixed with "→"

Be specific. Use the actual numbers when they add value. \
Do not pad with generic safety advice. Write in English.\
"""

# ─────────────────────────────────────────────────────────────────────────────
# SCORE LEGEND  (injected into every prompt so the model understands the metrics)
# ─────────────────────────────────────────────────────────────────────────────

_SCORE_LEGEND = """\
SCORING SYSTEM (all 0–100):
• fly_score        — final hourly score (shown as VETO if any hard block applies; 0=worst, 100=perfect)
• potential_score  — what fly_score would be without active vetoes
• launch_score     — launch conditions: wind direction, speed, gusts, low cloud
• upper_wind_score — upper-atmosphere quality: 925 / 850 / 800 / 700 hPa winds
• thermal_score    — thermal conditions: lapse rate, shortwave radiation, CAPE, T–Td spread
• risk_score       — risk level: LOWER = MORE risk (gusts, rain, lightning potential)
• foehn_score      — foehn influence: HIGHER = MORE foehn (0 = none, 100 = severe)
• veto type        — hard block: wind | gusts | precipitation | foehn | visibility\
"""

# ─────────────────────────────────────────────────────────────────────────────
# CONTEXT BUILDER
# ─────────────────────────────────────────────────────────────────────────────

def _s(v: Any, d: float = 0.0) -> float:
    """Return v if not None, else d."""
    return v if v is not None else d


def build_day_context(
    evaluated_all: List[Dict[str, Any]],
    rows_all: List[Dict[str, Any]],
    site,        # SiteConfig (imported at call-time to avoid circular import)
    day: str,
) -> str:
    """Return a compact, LLM-readable string summarising the flying day (09–19)."""
    from core import wind_dir_label  # local import — avoids circular dependency

    rbt = {r["time"]: r for r in rows_all}
    hrs = [
        h for h in evaluated_all
        if h["time"].startswith(day) and 9 <= int(h["time"][11:13]) <= 19
    ]
    if not hrs:
        return f"No forecast data available for {day}."

    north_name = getattr(site, "foehn_north_name", "") or f"{site.foehn_north_lat:.2f}°N/{site.foehn_north_lon:.2f}°E"
    south_name = getattr(site, "foehn_south_name", "") or f"{site.foehn_south_lat:.2f}°N/{site.foehn_south_lon:.2f}°E"

    lines: List[str] = [
        f"SITE: {site.name}",
        f"  Launch window  : {site.launch_dir_center_deg:.0f}° ± {site.launch_dir_tolerance_deg:.0f}°",
        f"  Wind limits    : launch ≤ {site.launch_wind_max_kmh:.0f} km/h  "
        f"gusts < {site.gust_max_kmh:.0f} km/h  "
        f"925 hPa ≤ {site.wind_925_max_kmh:.0f} km/h",
        f"  Foehn threshold: ΔP N–S > {site.foehn_delta_p_max_hpa:.1f} hPa (veto at 120% = {site.foehn_delta_p_max_hpa * 1.2:.1f} hPa)",
        f"  Foehn stations : {north_name} (windward) → {south_name} (lee)",
        "",
        f"DATE: {day}",
        "",
        _SCORE_LEGEND,
        "",
        "HOURLY FORECAST (09:00–19:00):",
        (
            "time   fly   pot  | Laun  UW   Thm  Risk Foehn"
            " | 10m-wind     gusts  925-wind     ΔP(hPa)"
            " | CldLo  Precip  SW(W/m²)  CAPE  FL(m)  inversions  | veto"
        ),
    ]

    for h in hrs:
        hour = h["time"][11:16]
        row  = rbt.get(h["time"], {})

        def rv(k: str, d: float = 0.0) -> float:
            return _s(row.get(k), d)

        def hv(k: str, d: float = 0.0) -> float:
            return _s(h.get(k), d)

        fly_str  = "VETO" if h.get("veto") else f"{hv('fly_score'):4.0f}"
        w10_dir  = wind_dir_label(rv("wind_direction_10m"))
        w925_dir = wind_dir_label(rv("wind_direction_925hPa"))

        # inversion detection: ΔT > 1 °C between adjacent levels = warmer aloft
        t2 = rv("temperature_2m")
        t9 = rv("temperature_925hPa")
        t8 = rv("temperature_850hPa")
        t7 = rv("temperature_700hPa")
        inv_parts: List[str] = []
        if t9 - t2 > 1: inv_parts.append(f"sfc-925+{t9-t2:.1f}°@750m")
        if t8 - t9 > 1: inv_parts.append(f"925-850+{t8-t9:.1f}°@1500m")
        if t7 - t8 > 1: inv_parts.append(f"850-700+{t7-t8:.1f}°@3000m")
        inv_str = ",".join(inv_parts) if inv_parts else "-"

        veto_str = h.get("veto_type") or "-"
        if h.get("veto") and h.get("veto_reasons"):
            veto_str += f"({','.join(h['veto_reasons'])})"

        lines.append(
            f"{hour}  {fly_str:4s}  {hv('potential_score'):4.0f}"
            f" | {hv('launch_score'):4.0f} {hv('upper_wind_score'):4.0f}"
            f" {hv('thermal_score'):4.0f} {hv('risk_score'):4.0f} {hv('foehn_score'):4.0f}"
            f" | {w10_dir:3s}{rv('wind_speed_10m'):4.0f}km/h"
            f" gu{rv('wind_gusts_10m'):4.0f}"
            f" {w925_dir:3s}{rv('wind_speed_925hPa'):4.0f}km/h"
            f" {rv('delta_p_foehn'):+5.1f}"
            f" | {rv('cloud_cover_low'):3.0f}%"
            f" {rv('precipitation'):4.1f}mm"
            f" {rv('shortwave_radiation'):6.0f}"
            f" {rv('cape'):5.0f}"
            f" {rv('freezing_level_height'):5.0f}"
            f"  {inv_str}"
            f" | {veto_str}"
        )

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# API CALL
# ─────────────────────────────────────────────────────────────────────────────

def get_advisory(day_context: str, api_key: str) -> str:
    """Call GPT-4o-mini and return the advisory text."""
    from openai import OpenAI  # local import — openai is optional dependency

    client   = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model="gpt-4o-mini-2024-07-18",
        messages=[
            {"role": "system", "content": _SYSTEM},
            {"role": "user",   "content": day_context},
        ],
        max_tokens=500,
        temperature=0.65,
    )
    return response.choices[0].message.content.strip()
