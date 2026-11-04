"""Small server-rendered SVG charts, with real gaps and HTML data alternatives."""

import math


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


def chart(title, unit, hours, series, lower=0, upper=None, note=""):
    # series: (label, accessor, token index). Missing values are never drawn as zero.
    lines = [{"label": label, "values": [getter(h) for h in hours], "color": color}
             for label, getter, color in series]
    values = [v for line in lines for v in line["values"] if v is not None]
    low = min([lower, *values])
    high = upper if upper is not None else max([1, *values]) * 1.12
    step = 10 ** math.floor(math.log10(max(high - low, 1)))
    if upper is None:
        high = math.ceil(high / step) * step
    x = lambda i: 48 + i * 672 / max(len(hours) - 1, 1)
    y = lambda v: 155 - (v - low) / max(high - low, 1) * 130
    for line in lines:
        line["segments"] = segments(line["values"], x, y)
        line["points"] = [{"x": x(i), "y": y(v), "value": v,
                           "time": hours[i]["time"][11:16]}
                          for i, v in enumerate(line["values"]) if v is not None]
    return {
        "title": title, "unit": unit, "note": note, "lines": lines,
        "ticks": [{"value": f"{low + (high - low) * i / 4:.3g}",
                   "y": y(low + (high - low) * i / 4)} for i in range(5)],
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
            *[(f"{level} hPa", raw(f"wind_speed_{level}hPa"), color)
              for level, color in [(925, 2), (850, 3), (800, 5), (700, 6)]]]),
        chart("Foehn pressure gradient", "hPa", hours,
              [("North − south · ICON EU", raw("delta_p_foehn"), 5)],
              note="Reference-station pressure difference, not a probability of foehn."),
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
            *[(f"{level} hPa", raw(f"temperature_{level}hPa"), color)
              for level, color in [(925, 2), (850, 3), (700, 5)]]],
              note="A warmer upper layer can indicate an inversion; pressure levels may lie below terrain."),
        chart("Relative humidity", "%", hours, [
            (f"{level} hPa", raw(f"relative_humidity_{level}hPa"), color)
            for level, color in [(925, 1), (850, 2), (800, 3), (700, 5)]], upper=100),
        chart("Temperature − dew point", "°C", hours, [("T − Td", spread, 2)],
              note="Rough cloudbase estimate = 125 × spread, metres above the model surface."),
        chart("Freezing level", "m AMSL", hours,
              [("0 °C level", raw("freezing_level_height"), 6)]),
        chart("Convective energy", "J/kg", hours, [("CAPE", raw("cape"), 5)],
              note="CAPE alone does not determine thunderstorm or flight safety."),
    ]
