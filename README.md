# Bombometro · Borant web preview

A FastAPI/Jinja interface for the existing Bombometro paragliding forecast engine.
It uses public Open-Meteo data and the original `core.py` and `sites.json` without
changing scoring formulas. It is an experimental forecast explorer, **not flight
clearance or a validated aviation forecasting system**.

## Run locally

```sh
uv sync --frozen
uv run uvicorn web:app --host 127.0.0.1 --port 8103 --no-access-log
```

Open `http://127.0.0.1:8103`. `/` is the landing page, `/app` the forecast explorer,
`/guide` explains scores and limitations, `/healthz` checks the process. No API key
or `.env` is required. The original Streamlit entry points and requirements remain
in the repository for comparison; this web version does not import them or the AI
advisor. Install the web version with `uv`, not the legacy requirements file.

## Included

- Grappa, Cavallaria and the experimental Meduno / Monte Valinis preset;
  five original model choices; up to five forecast days.
- Day classifications, model windows, sunrise/noon/sunset, hourly veto reasons.
- SVG verdict faces and a matching set of regime icons in day cards, the timeline,
  chart tooltips and hourly evidence. Hover, focus or tap a regime control for its
  name and explanation; `/guide#regime-symbols` lists the whole set. A crossed clock
  distinguishes the engine's `short` fallback when no qualifying window exists.
  There is no new meteorological classification or scoring change.
- Twelve lightweight server-rendered SVG charts and exact per-hour source values.
- T−Td includes a dashed derived cloudbase with a right-hand AGL metre axis;
  freezing-level ticks use readable whole metres instead of scientific notation.
  The wind table follows the plots, immediately before hourly evidence.
- The foehn pressure plot always has a symmetric axis around a labelled, emphasized
  zero reference. Wind, temperature and humidity legends/tooltips include approximate
  pressure-level altitudes in metres AMSL, using the same mapping as the wind table.
- Wind-by-altitude table: 700/800/850/925 hPa, gusts and 10 m wind against local
  forecast hours, with direction and horizontal scrolling on mobile. The cell
  heatmap runs from blue at zero through cyan and amber to red at/above the site's
  configured limit for that row (31 shades). Each row shows its red threshold;
  missing speeds stay grey. Colours use unrounded values, not a safety verdict.
  Direction arrows point downwind; the small compass label states the wind's
  origin. Calm and unavailable directions do not acquire an arrow.
- Unified plot tooltips show every series at the selected hour, including wind
  directions, vetoes and missing values. Hover, tap, or focus a plot and use arrow
  keys; Home/End select the first/last hour and Escape dismisses the tooltip.
- Borant dark/light themes, native forms and disclosures, responsive layout.
- 30-minute per-site/model memory cache; same-key requests coalesce, different
  selections do not wait behind each other's network requests. Failure backoff: 60s.
- Missing inputs suppress scores instead of being silently replaced by zero.
  All 15 samples from 06:00 to 20:00 must be complete for a daily verdict.
  The first source hour cannot be scored without its previous-hour trend inputs.
- Clear pressure source (ICON EU for every model), retrieval time and grid metadata.

## Deliberately not included

AI advice, paid requests, user accounts, site editing, database persistence,
internationalisation, Borant ID integration and production deployment. The UI is
entirely English, with no placeholder language selector. A lab proxy supplies
authentication. **Do not expose this app directly to the public internet.**

The existing upstream compose file belongs to the old deployment. It is not a
deployment recipe for this preview. See [DEPLOY.md](DEPLOY.md).

## Data and model limitations

### Meduno / Monte Valinis

Added on 5 November 2026. The launch-area coordinates are converted from the
[municipal page](https://www.medunoinvolo.it/it/c/869321/il-monte-valinis) and
[Adventure school's site page](https://scuolaparapendioadventure.it/dovevoliamo):
46°13′49.93″ N, 12°48′23.73″ E → 46.230536, 12.806592.

The owner corrected the initial SE–SW assumption on 5 November 2026 with an
annotated map and explicit confirmation that north is at the top. The configured
sector is now **S–SW–W: 225° ± 45°, wind from 180°–270°**, not downwind bearings.
This confirms direction only, not an hour's flyability or safe wind speeds.
Numerical thresholds and the Innsbruck–Bolzano
pressure proxy are inherited from Grappa, **not locally calibrated**. The sources
disagree on launch elevation: Adventure says 1,100 m; [Paragliding Map](https://www.paraglidingmap.com/regions/meduno)
distinguishes a 975 m main launch and a 1,088 m summit launch. No single launch
height is asserted or injected into the weather request. The catalogue warns
about easterly flow/turbulence; the engine has no dedicated Bora veto. The nominal
925 hPa level is below both reported launch heights.

The UI shows the experimental warning before the forecasts, plus sourced notes
and links to the operator's FlyCard/LI-R427 information. These do not replace
current local permissions, airspace or NOTAM checks. `site_details.py` holds the
notes outside the legacy `SiteConfig` schema. The old two presets and scoring
formulas were not changed.

### General limitations

The original scoring arithmetic is not validated by this conversion. In particular,
the thermal attenuation of foehn remains an inherited heuristic. Pressure levels
may lie below the terrain; surface wind is not observed launch wind. A cloudbase
estimate is above the model surface, not AMSL. Full-day summaries include hours
already passed and may include darkness. Window length counts hourly samples.

Model coverage and returned fields differ. Live checks on 4 November 2026 found
complete daytime inputs for five days with ICON EU at Grappa, four complete days
with Météo-France, and missing pressure-level scoring inputs with ECMWF IFS,
MeteoSwiss CH1 and ItaliaMeteo ICON 2I. Those models remain inspectable, but the
preview honestly withholds classifications where inputs are absent. This is an
observation about that API response, not a permanent guarantee about any model.

The old advisor's risk legend is reversed, and the final interpretation table in
the old `SCORING_MANUAL.md` contradicts the engine for risk and foehn. The new guide
uses the code's direction: **higher risk and foehn are worse**. The old manual and
advisor are retained as upstream files, not served as authoritative web guidance.

## Tests

```sh
uv run pytest -q
uv run playwright install chromium
# With the preview running and Chromium system libraries available:
uv run python tests/browser_check.py
```

The public API fixture is only used by tests; the application never substitutes
it for live data. See [TESTING.md](TESTING.md) for the checks actually performed.

## Privacy and state

No personal records, accounts or application database. The browser stores only
`bombometro-theme` in local storage. Site/model choices are sent to this server;
public site coordinates are sent to Open-Meteo. Access logging is disabled in the
launch command. The reverse proxy has its own logging policy. Weather cache is
rebuildable and disappears on restart; there is no irreplaceable application state.

Forecast data: [Open-Meteo](https://open-meteo.com/), CC BY 4.0. Baseline engine:
`that-ugly-cat/bombometro`, commit `ffe3a58`.

Web adaptation: Ono · dedalo · gpt-6-astra-fast.
