# Public weather fixture

`open_meteo.json` contains the first 24 hours from an actual public API response
retrieved during the workshop implementation on 4 November 2026. Grappa, ICON EU,
five-day request, Europe/Rome; pressure series: Innsbruck minus Bolzano, ICON EU.
Fields, units, nulls and coordinates are retained. The unused lightning-potential
field is null in the original response. No personal data or credentials.

Source: https://open-meteo.com/ · CC BY 4.0.
Tests use this shape to establish wrapper parity, not forecast accuracy. The
application never loads this fixture or presents it as a live forecast.

Ono · dedalo · gpt-6-astra-fast
