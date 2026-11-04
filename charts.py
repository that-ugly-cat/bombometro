"""Small server-rendered SVG charts, with real gaps and HTML data alternatives."""

import math

from core import wind_dir_label


REGIME_LABELS = {"cap": "capped", "capped": "capped", "blue": "blue thermals",
                 "cumulus": "cumulus", "off": "inactive", "stable": "stable",
                 "short": "short window", "technical": "technical", "foehn": "foehn",
                 "unclassified": "unclassified"}


def regime_label(code):
    return REGIME_LABELS.get(code, "unclassified")


PRESSURE_ALTITUDES = {925: 750, 850: 1500, 800: 1950, 700: 3000}


def pressure_label(level):
    return f"{level} hPa · ≈ {PRESSURE_ALTITUDES[level]:,} m AMSL"


WIND_LEVELS = (
    *((f"{level} hPa", f"≈ {PRESSURE_ALTITUDES[level]:,} m AMSL", f"{level}hPa")
      for level in (700, 800, 850, 925)),
    ("Gusts", "10 m above model surface", None),
    ("10 m wind", "Above model surface", "10m"),
)


def wind_color(speed, limit):
    """Thirty bounded colour steps; the red endpoint starts at the row's limit."""
    if speed is None:
        return "wind-unknown"
    step = math.floor(max(0, min(speed / limit, 1)) * 30)
    segment = min(step // 10, 2)
    return f"wind-heat wind-range-{segment} wind-mix-{step - segment * 10}"


def wind_table(hours, site):
    """High-to-low pressure levels, with missing speed and direction kept distinct."""
    rows = []
    for label, altitude, level in WIND_LEVELS:
        limit = (site.gust_max_kmh if level is None else site.launch_wind_max_kmh
                 if level == "10m" else getattr(site, f"wind_{level[:-3]}_max_kmh"))
        cells = []
        for hour in hours:
            raw = hour["raw"]
            speed = raw.get(f"wind_speed_{level}" if level else "wind_gusts_10m")
            direction = raw.get(f"wind_direction_{level}") if level else None
            cells.append({"speed": speed, "direction": direction,
                          "compass": wind_dir_label(direction) if direction is not None else None,
                          "color_class": wind_color(speed, limit), "has_direction": level is not None})
        rows.append({"label": label, "altitude": altitude, "limit": limit, "cells": cells})
    return rows


def segments(values, x, y):
    paths, points = [], []
    for i, value in enumerate(values):
        if value is None:
            if points:
                paths.append(" ".join(points))
                points = []
        else:
            points.append(f"{x(i):.1f},{y(value):.1f}")
    if points:
        paths.append(" ".join(points))
    return paths


def chart(title, unit, hours, series, lower=0, upper=None, note="", directions=None,
          secondary=None, altitude_ticks=False, centered_zero=False):
    # series: (label, accessor, token index). Missing values are never drawn as zero.
    lines = [{"label": label, "values": [getter(h) for h in hours], "color": color,
              "unit": unit, "secondary": False}
             for label, getter, color in series]
    values = [v for line in lines for v in line["values"] if v is not None]
    low = min([lower, *values])
    high = upper if upper is not None else max([1, *values]) * 1.12
    step = 10 ** math.floor(math.log10(max(high - low, 1)))
    if upper is None:
        high = math.ceil(high / step) * step
    if centered_zero:
        magnitude = max((abs(v) for v in values), default=0)
        if magnitude == 0:
            high = 1.0
        else:
            scale = 10 ** math.floor(math.log10(magnitude))
            high = math.ceil(magnitude * 1.12 / scale) * scale
        low = -high
    # Wider left margin keeps metre labels inside the SVG, including commas.
    left, right = 82, 660 if secondary else 720
    if altitude_ticks:
        interval = next((s for s in (250, 500, 1000, 2000, 5000) if (high - low) / s <= 5), 10000)
        low = math.floor(low / interval) * interval
        high = max(low + interval, math.ceil(high / interval) * interval)
        tick_values = list(range(int(low), int(high) + 1, interval))
    else:
        tick_values = [low + (high - low) * i / 4 for i in range(5)]
    x = lambda i: left + i * (right - left) / max(len(hours) - 1, 1)
    y = lambda v: 155 - (v - low) / (high - low) * 130
    if secondary:
        label, getter, color, secondary_unit, factor = secondary
        lines.append({"label": label, "values": [getter(h) for h in hours],
                      "color": color, "unit": secondary_unit, "secondary": True})
    for line in lines:
        project_y = (lambda v: y(v / factor)) if line["secondary"] else y
        line["segments"] = segments(line["values"], x, project_y)
        line["points"] = [{"x": x(i), "y": project_y(v), "value": v,
                           "time": hours[i]["time"][11:16]}
                          for i, v in enumerate(line["values"]) if v is not None]
    hover = []
    for i, hour in enumerate(hours):
        readings = []
        for line in lines:
            value = line["values"][i]
            display = "—" if value is None else f"{value:.1f}"
            if value is not None and directions and line["label"] in directions:
                direction = hour["raw"].get(directions[line["label"]])
                display += (f" · {wind_dir_label(direction)} ({direction:.0f}°)"
                            if direction is not None else " · direction unavailable")
            if value is None and line["label"] == "Fly score" and hour.get("veto"):
                display = "Veto"
            if secondary:
                display += " " + line["unit"]
            readings.append({"label": line["label"], "value": display, "color": line["color"],
                             "unit": line["unit"]})
        hover.append({"time": hour["time"][11:16], "x": x(i), "readings": readings,
                      "regime": regime_label(hour.get("thermal_regime")) if hour["complete"] else "unclassified",
                      "status": ("Scoring inputs incomplete" if not hour["complete"] else
                                 "Veto: " + "; ".join(hour["veto_reasons"]) if hour.get("veto") else "")})
    return {
        "title": title, "unit": unit, "note": note, "lines": lines, "hover": hover,
        "left": left, "right": right, "secondary": bool(secondary),
        "secondary_unit": secondary_unit if secondary else "",
        "centered_zero": centered_zero,
        "ticks": [{"value": f"{v:,.0f}" if altitude_ticks else f"{v:g}", "y": y(v),
                   "zero": centered_zero and v == 0} for v in tick_values],
        "right_ticks": [{"value": f"{v * factor:,.0f}", "y": y(v)} for v in tick_values] if secondary else [],
        "labels": [{"text": h["time"][11:13], "x": x(i)}
                   for i, h in enumerate(hours) if i % 2 == 0],
    }


def day_charts(hours):
    def score(key):
        return lambda h: h.get(key) if h["complete"] else None

    def raw(key):
        return lambda h: h["raw"].get(key)

    def spread(h):
        a, b = h["raw"].get("temperature_2m"), h["raw"].get("dew_point_2m")
        return a - b if a is not None and b is not None else None

    def cloudbase(h):
        value = spread(h)
        return round(max(0, value) * 125, 0) if value is not None else None

    return [
        chart("Score & potential", "/ 100", hours, [
            ("Fly score", score("fly_score"), 1),
            ("Potential", score("potential_score"), 6)], upper=100,
            note="Potential ignores vetoes and penalties. A gap is not a zero."),
        chart("Score components", "/ 100", hours, [
            ("Launch", score("launch_score"), 1),
            ("Upper wind", score("upper_wind_score"), 2),
            ("Thermal", score("thermal_score"), 3),
            ("Risk", score("risk_score"), 4),
            ("Foehn", score("foehn_score"), 5)], upper=100,
            note="Risk and foehn: higher is worse. Other components: higher is better."),
        chart("Wind by level", "km/h", hours, [
            ("10 m", raw("wind_speed_10m"), 1),
            ("Gusts", raw("wind_gusts_10m"), 4),
            *[(pressure_label(level), raw(f"wind_speed_{level}hPa"), color)
              for level, color in [(925, 2), (850, 3), (800, 5), (700, 6)]]],
              directions={"10 m": "wind_direction_10m", **{
                  pressure_label(level): f"wind_direction_{level}hPa" for level in (925, 850, 800, 700)}},
              note="Pressure-level heights are approximate metres above sea level (AMSL), not above the launch; levels may lie below terrain."),
        chart("Foehn pressure gradient", "hPa", hours,
              [("North − south · ICON EU", raw("delta_p_foehn"), 5)],
              centered_zero=True,
              note="Centred on 0 hPa: north minus south reference pressure. Positive and negative departures use the same scale; this is not a probability of foehn."),
        chart("Cloud cover", "%", hours, [
            ("Low", raw("cloud_cover_low"), 1), ("Mid", raw("cloud_cover_mid"), 2),
            ("High", raw("cloud_cover_high"), 6)], upper=100,
            note="Independent layers, not stacked: their sum is not total cloud cover."),
        chart("Precipitation", "mm", hours, [("Precipitation", raw("precipitation"), 1)],
              note="Hourly accumulation. Snowfall is listed separately in hourly details."),
        chart("Solar input", "W/m²", hours,
              [("Shortwave radiation", raw("shortwave_radiation"), 3)]),
        chart("Temperature profile", "°C", hours, [
            ("2 m", raw("temperature_2m"), 1),
            *[(pressure_label(level), raw(f"temperature_{level}hPa"), color)
              for level, color in [(925, 2), (850, 3), (700, 5)]]],
              note="A warmer upper layer can indicate an inversion. Heights are approximate m AMSL, not above the launch; levels may lie below terrain."),
        chart("Relative humidity", "%", hours, [
            (pressure_label(level), raw(f"relative_humidity_{level}hPa"), color)
            for level, color in [(925, 1), (850, 2), (800, 3), (700, 5)]], upper=100,
              note="Heights are approximate m AMSL, not above the launch; pressure levels may lie below terrain."),
        chart("Temperature − dew point", "°C", hours, [("T − Td", spread, 2)],
              secondary=("Cloudbase estimate", cloudbase, 3, "m AGL", 125),
              note="Left: T − Td (°C). Right: cloudbase ≈ 125 × max(T − Td, 0), metres above the model surface (AGL), not AMSL. The derived dashed line overlaps the spread where positive."),
        chart("Freezing level", "m AMSL", hours,
              [("0 °C level", raw("freezing_level_height"), 6)], altitude_ticks=True),
        chart("Convective energy", "J/kg", hours, [("CAPE", raw("cape"), 5)],
              note="CAPE alone does not determine thunderstorm or flight safety."),
    ]
