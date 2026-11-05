# Verification record

4 November 2026 · Ono · dedalo · gpt-6-astra-fast

## Automated

`uv run pytest -q`: 54 tests pass. Coverage includes:

- equality with upstream scoring output for complete hours at both site presets;
- every required scoring field missing individually, previous-hour trend gaps,
  absent optional diagnostics, short arrays, nonfinite values and malformed times;
- first hour without a predecessor, metadata validation, and no fictitious mean
  for a day with no qualifying window;
- cache keys/expiry, request coalescing, independent-key fetches, failure backoff
  and no stale response on failed refresh;
- fixed provider request errors, timestamp-based pressure joins, chart gaps and
  distinct fractional axis labels;
- landing/workspace/guide/health routes, real form parameters, invalid selections,
  rendered data completeness and user-visible network failure.

One dependency warning remains: Starlette's TestClient deprecates its httpx
transport in favour of httpx2. It does not affect the runtime service.

## Live data and browser

- Local health and rendered forecast: HTTP 200, actual Open-Meteo data.
- Both site selections exercised in Chromium, including form submission and date
  navigation. Five model choices at Grappa return HTTP 200 and 12 rendered charts.
- ICON EU: five complete daytime summaries. Météo-France: one of five incomplete.
  ECMWF IFS, MeteoSwiss CH1 and ItaliaMeteo ICON 2I: all five unclassified because
  required pressure-level inputs are absent. No zero-filled replacement scoring.
- Chromium: dark/light themes at widths 1440, 768, 390 and 320 px. No horizontal
  page overflow. Theme survives reload; hour selection opens the relevant evidence.
- No JavaScript page errors during the tested flow. Landing and guide also checked
  at 320 px. Screenshots inspected for desktop dark and mobile light.
- Computed contrast for 15 populated text categories: minimum 7.23:1 in dark and
  5.82:1 in light. This is a targeted contrast check, not a full accessibility audit.
- Process confirmed listening only on 127.0.0.1:8103. External unauthenticated
  request rejected with HTTP 401. Authenticated external login not tested here.

Browser libraries unavailable on the host were extracted from distribution
packages inside ignored `runtime/browser-libs`; no root installation was used.
Screenshots and machine-readable browser/model reports are in ignored `runtime/`.

## Review

Bastian (gpt-6.1-sol) reviewed the implementation read-only. All four concrete
findings were corrected and covered by tests: missing initial trend, global fetch
lock, no-window mean, and malformed grid metadata. This review and the tests do
not validate the meteorological heuristics or certify flight safety.

## Follow-up: wind matrix and unified tooltips

4 November 2026 · Ono · dedalo · gpt-6-astra-fast

Added the requested wind-by-altitude matrix and whole-plot hourly tooltips.
`uv run pytest -q`: **58 tests pass**. New tests cover table order/values, calm
versus unknown wind, tooltip parity with the plotted arrays, missing/veto labels,
wind-from directions, and twelve distinct tooltip IDs and JSON payloads.

Extended live Chromium checks pass for every plot in both themes at 1440 and
320 px: hover selects the expected hour, every displayed value matches the chart
payload, tooltip stays within the viewport, arrow/Home/End navigation works and
Escape dismisses it. Six table rows and 90 hourly cells are present. Horizontal
table scrolling works without widening the page at 1440/768/390/320 px.
An initial mobile overflow caused by absolutely positioned screen-reader labels
was reproduced and fixed by positioning their scroll container.

A separate touch-enabled mobile browser context confirms tap selection and
outside-tap dismissal. Inspected the mobile wind tooltip screenshot; no JavaScript
page errors. As before, these are browser emulation checks, not physical-device
tests or an authenticated external login test.

## Follow-up: wind direction arrows

4 November 2026 · Ono · dedalo · gpt-6-astra-fast

The table now uses SVG arrows pointing downwind, with a small wind-from compass
label and an explicit legend. Calm, unavailable directions and gusts have no
invented directional arrow. **63 automated tests pass**, including the four
cardinal rotations and calm/missing/gust handling. Live Chromium checks confirm
rendered arrows, no page overflow and no JavaScript errors in both themes at
1440, 390 and 320 px. The desktop dark table screenshot was inspected.

## Follow-up: blue-to-red wind heatmap

4 November 2026 · Ono · dedalo · gpt-6-astra-fast

Replaced the four fixed speed bands with 31 blue/cyan/amber/red shades, normalized
to each row's configured site limit. Zero is blue, the exact limit and higher
values are red, missing speeds remain grey. Row headers disclose the thresholds;
the legend distinguishes reference limits from hard vetoes. Scoring is unchanged.

**70 automated tests pass**, including endpoints, just-below-limit values, clipping
and per-level limits. The extended Chromium suite passes: all 31 computed colours
are distinct in each theme, the endpoints equal the palette tokens, and minimum
text/arrow contrast across the complete scale is **6.38:1 dark / 9.04:1 light**.
Responsive layout, table scrolling, all plot tooltips and touch interaction were
rechecked. Inspected the live desktop heatmap screenshot.

## Follow-up: ordering, regimes, altitude axes and verdict faces

4 November 2026 · Ono · dedalo · gpt-6-astra-fast

Moved the wind table immediately before hourly evidence. Restored inherited daily
regime badges and explicit hourly thermal-regime labels. Added decorative SVG faces
for the five verdicts, retaining the text labels; unclassified data has no invented
face. No scoring formulas changed.

The old `.3g` tick formatting could turn freezing heights into scientific notation.
Freezing-level ticks now use whole metres with thousands separators and regular
intervals; all Y labels are larger and have a wider margin. T−Td adds a dashed
cloudbase estimate and proportional right-hand metre-AGL axis, with per-series
tooltip units. The guide explains why the derived curves overlap and distinguishes
model-surface AGL from AMSL. Null inputs remain gaps; negative spread clamps the
cloudbase estimate to zero, as in the original engine.

**81 automated tests pass**, including ordering, all five face variants, unknown
verdicts, regime names, altitude tick formatting, secondary-axis conversion and
null/negative spread. The live Chromium suite passes in both themes at four widths;
tooltips still select the correct hour after plot margins changed. Verified all
altitude tick labels fit inside their SVG at 1440/390/320 px and inspected the
freezing-level, dual-axis and verdict-card screenshots.

## Follow-up: compact mobile wind labels

4 November 2026 · Ono · dedalo · gpt-6-astra-fast

Measured the sticky altitude column at 145 px on both desktop and mobile. Below
761 px it is now 88 px (39% narrower), with wrapped labels and unchanged font
sizes. The desktop width remains 145 px. No altitude or reference limit is hidden.
The extended live browser suite passes in both themes at 1440/768/390/320 px:
all seven first-column cells have the expected width, no label overflows, the
column remains pinned while scrolling, and the page does not widen. Inspected
the 390 px table screenshot. Existing tooltip, axis and heatmap checks also pass.

## Follow-up: foehn zero and pressure-level altitudes

4 November 2026 · Ono · dedalo · gpt-6-astra-fast

Reproduced the missing zero tick with an all-negative pressure series: the old
ticks were -3.1, -1.825, -0.55, 0.725 and 2 hPa. The foehn pressure plot now has a
symmetric domain and five ticks, always including zero at the vertical midpoint,
with a stronger dashed reference line. Sub-hPa ranges also use their actual span.

Wind, temperature and humidity legends and tooltips now show the approximate
750/1,500/1,950/3,000 m AMSL counterparts of 925/850/800/700 hPa. One shared mapping
also supplies the wind-table altitudes. Notes retain the distinction from height
above launch and warn that pressure levels can fall below terrain.

**92 automated tests pass**, including negative-only, positive-only, mixed,
all-zero, sub-hPa, missing and empty pressure series; shared altitude labels; wind
direction retention; and the rendered zero line. The live Chromium suite passes
in both themes at 1440/768/390/320 px, including tooltip row-fit checks for the
longer labels. Inspected the mobile touch tooltip and visible foehn zero reference.

## Follow-up: regime icon family

5 November 2026 · Ono · dedalo · gpt-6-astra-fast

Added ten local SVG symbols: inactive, blue thermals, cumulus, capped, stable
window, short window, no qualifying window, technical, foehn and unclassified.
Names/descriptions live in `regimes.py`; aliases resolve there. The crossed-clock
variant applies only to the engine's `short` tag without a qualifying window.
No source score or summary is changed.

Day-card and timeline icon controls are siblings of their navigation links, not
nested buttons. Hover/focus shows a viewport-bounded explanation; click/tap pins
it, a second activation, outside click/tap or Escape dismisses it. Screen-reader
labels carry the full meaning, and an always-available guide lists all symbols.
Hourly evidence explains its symbol when expanded; chart tooltips combine the
icon with its name and explanation. Inactive and missing data remain distinct.

**108 automated tests pass**, covering aliases, invalid codes, the no-window
variant, SVG symbol coverage, accessible names and the complete guide. The live
Chromium suite passes in dark/light at 1440/768/390/320 px, including actual SVG
rendering, hover/keyboard dismissal, viewport fit and unchanged day/hour navigation.
Touch-enabled checks confirm that tapping a day or hour icon opens its explanation
without navigating, and outside tap closes it. Corrected hover reopening after a
resize and a queued scroll event during automatic focus scrolling. Existing chart,
heatmap, axis, mobile-table and contrast checks still pass. Inspected the desktop
icon key, live forecast and mobile chart tooltip screenshots.

## Follow-up: experimental Meduno / Monte Valinis preset

5 November 2026 · Ono · dedalo · gpt-6-astra-fast

Added Meduno at the launch-area coordinates published by the municipality and
Adventure school. The site-specific warning precedes results, including on an
upstream error page. Expandable notes distinguish sourced coordinates, conflicting
elevations, an assumed south-facing sector and inherited/unvalidated thresholds
and pressure references. Landing-page site count now derives from configuration;
cache capacity naturally expands to 15 site/model combinations.

**115 automated tests pass**, including DMS conversion, inherited parameters,
dynamic cache keys, site selection, disclosure order, source URLs, network-error
disclosure and sector behaviour. The upstream comparison test now also exercises
Meduno. A Git comparison confirmed that `core.py` and both existing site entries
are unchanged.

Live ICON EU response: 120 hourly records, five days, 15 complete daytime hours
per day. Returned grid coordinates/elevation: 46.25, 12.8125, 983 m; these are
provider metadata, not a resolution of the published launch-height disagreement.
All five model selections return HTTP 200, 12 charts and the experimental warning;
this does not mean every model has all scoring inputs. The live Chromium suite
passes, including Meduno selection through the actual form and opening the source
notes (three cited links) at 320 px without horizontal overflow. Inspected
the rendered mobile notes. Runtime service health passes and logs show no errors.

Bastian (gpt-6.1-sol) reviewed the preset, disclosures and the three source pages
read-only: no concrete concealed limitation found. His review did not validate
meteorological thresholds, certify local permissions, or run tests. Those limits
remain explicit in the application and README.
