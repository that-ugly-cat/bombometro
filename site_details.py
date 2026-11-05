"""Sourced site notes, kept outside the legacy engine's configuration schema."""

SITE_DETAILS = {
    "Meduno": {
        "name": "Meduno · Monte Valinis",
        "checked_on": "2026-11-05",
        "warning": (
            "Experimental site preset: numerical limits and the Innsbruck–Bolzano pressure "
            "proxy are inherited from Grappa, not locally calibrated. The S–SW–W wind-from "
            "sector (180°–270°) was supplied and confirmed by the owner on 5 November 2026."
        ),
        "notes": [
            ("Coordinates", "The municipality's Meduno in Volo page and Adventure school both give "
             "46°13′49.93″ N, 12°48′23.73″ E for the launch area. Converted to decimal: "
             "46.230536, 12.806592. This preset is for the Monte Valinis launch area, not the town centre."),
            ("Elevation unresolved", "Adventure lists the launch at 1,100 m AMSL. Paragliding Map "
             "lists the main launch at 975 m and a separate summit launch at 1,088 m. These are "
             "not interchangeable measurements. No single surveyed launch height is asserted or "
             "sent as an elevation override to Open-Meteo; its returned grid height remains separate."),
            ("Owner-confirmed wind sector", "On 5 November 2026 the owner annotated the launch "
             "directions on a map and explicitly confirmed that north is at the top. The "
             "south–southwest–west sector replaces the initial SE–SW assumption: wind from "
             "180° through 270°, configured as 225° ± 45°. These are wind-from bearings; "
             "do not reverse them like the downwind arrows in the wind table. This confirms "
             "the sector, not the numerical wind/gust limits or suitability of a particular hour."),
            ("Easterly-flow warning", "Paragliding Map describes southerly wind at launch and warns "
             "that easterly flow away from launch can become turbulent even when launch wind "
             "appears southerly. "
             "The current engine has no dedicated Bora/easterly-flow veto."),
            ("Inherited thresholds", "Wind, gust, precipitation, cloud and foehn thresholds are "
             "copied from the existing Grappa preset. They are software heuristics, not locally "
             "approved flight limits. Innsbruck minus Bolzano is retained only as a regional "
             "pressure proxy; it is not a validated Meduno foehn detector."),
            ("Pressure levels", "The nominal 925 hPa level (about 750 m AMSL) is below both "
             "published launch heights. The inherited engine still uses it; do not interpret "
             "it as a measured wind layer above this launch."),
            ("Local operation", "Adventure warns of strong wind around the middle of the day, "
             "requires a FlyCard and publishes the LI-R427 operating documents. Check the "
             "current local rules, airspace and NOTAMs with the operator. This app neither "
             "checks permissions nor establishes airspace clearance."),
        ],
        "sources": [
            {"label": "Comune di Meduno · launch-area coordinates",
             "url": "https://www.medunoinvolo.it/it/c/869321/il-monte-valinis"},
            {"label": "Adventure school · site description and operating documents",
             "url": "https://scuolaparapendioadventure.it/dovevoliamo"},
            {"label": "Paragliding Map · main/summit launches and easterly-wind warning",
             "url": "https://www.paraglidingmap.com/regions/meduno"},
        ],
    },
}
