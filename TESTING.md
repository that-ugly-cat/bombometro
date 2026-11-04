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
