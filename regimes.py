"""Presentation vocabulary, not a second meteorological classifier."""

REGIMES = {
    "inactive": ("Inactive", "The model does not classify thermal activity as active. This is not a flight veto."),
    "blue": ("Blue thermals", "The model suggests thermals without cumulus markers."),
    "cumulus": ("Cumulus", "The model suggests thermals with cumulus formation."),
    "capped": ("Capped", "The model suggests cloud cover limiting thermal development."),
    "stable": ("Stable window", "A longer qualifying window without another dominant tag. Not a diagnosis of atmospheric stability."),
    "short": ("Short window", "A brief or isolated qualifying window in the model forecast."),
    "no-window": ("No qualifying window", "No hourly sequence meets the engine's window criteria. The crossed clock does not promise a short opportunity."),
    "technical": ("Technical", "Elevated model risk or technicality. Inspect the hourly reasons and limits."),
    "foehn": ("Foehn", "An elevated model foehn signal, not an observation of local wind conditions."),
    "unclassified": ("Unclassified", "Required inputs are unavailable, so no regime is assigned."),
}
REGIME_LABELS = {"cap": "capped", "capped": "capped", "blue": "blue thermals",
                 "cumulus": "cumulus", "off": "inactive", "stable": "stable",
                 "short": "short window", "technical": "technical", "foehn": "foehn",
                 "unclassified": "unclassified"}


def regime_label(code):
    return REGIME_LABELS.get(code, "unclassified")


def regime_info(code, has_window=True):
    key = {"off": "inactive", "cap": "capped", "no-data": "unclassified"}.get(code, code)
    if key not in REGIMES:
        key = "unclassified"
    if key == "short" and not has_window:
        key = "no-window"
    label, description = REGIMES[key]
    return {"key": key, "label": label, "description": description}
