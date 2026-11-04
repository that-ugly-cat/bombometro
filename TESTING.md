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
