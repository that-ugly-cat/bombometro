# Bombometro: public deployment handover for Claude Code

Prepared 5 November 2026 · Ono · dedalo · gpt-6-astra-fast

## Mandate and exact delivery

The owner chose **public, anonymous access** and asked Dedalo to prepare the
deployment. Production has **not** been changed. The workshop does not have a
permitted Bombometro deployment entry (`borant-ctl` returns `E_APP`) and its shell
cannot access the local Docker daemon. Do not turn those refusals into alternative
privileged paths on the workshop host. This handover is for the owner's operator
session, with its own production access.

This directory contains:

- `bombometro.bundle`: the complete committed branch `dedalo/borant-lab`, including
  its upstream ancestry; no dependency on an unpushed ancestor in another clone;
- `RELEASE.json`: exact commit/branch, decision and verification status;
- `Caddyfile.bombometro`: generated replacement host block for
  **bombometro.borant.eu → 127.0.0.1:8502**, intentionally without Borant ID;
- this handover and `SHA256SUMS`.

Verify every hash before importing the bundle (`sha256sum -c SHA256SUMS`, or
PowerShell `Get-FileHash` with SHA256). Verify the bundle in a review clone and
compare the fetched head with `RELEASE.json`. Do not overwrite the live checkout
with a source-directory copy, and do not copy `.env`, `.venv` or workshop caches.

## What changed

Streamlit presentation is replaced by FastAPI/Jinja and local SVG/JavaScript.
The inherited scoring engine is unchanged. Grappa and Cavallaria keep their old
settings; Meduno is added with an owner-confirmed 225° ±45° wind-from sector and
explicitly provisional numeric/foehn limits. Missing inputs suppress scores.
The UI includes day/regime icons, twelve plots, hover/touch/key tooltips, wind
matrix and dark/light themes. The AI advisor is not connected or in the image.

Production preparation adds a non-root/read-only Dockerfile, an updated Compose,
public Caddy generator, explicit mode/host/revision validation, bounded application
and upstream load, hashed theme bootstrap CSP, and a read-only acceptance script.
No application database, account or migration is introduced.

## What is proven, and what is not

The exact machine-readable status is in `RELEASE.json`; details and test commands
are in the delivered repository's `TESTING.md` and `DEPLOY.md`.

Proven on the workshop host:

- automated tests, including public mode, host/method validation, concurrency,
  budget/backoff and missing-data acceptance;
- a fresh `uv sync --frozen --no-dev --no-install-project` runtime, without
  Streamlit/OpenAI/test dependencies;
- public-mode HTTP smoke with real ICON EU data for all three sites;
- Chromium desktop/mobile, two themes, CSP-compatible theme persistence, icons,
  tooltips, navigation, contrast and narrow wind-table behaviour;
- real 429/503 load rejection and subsequent healthy process response;
- expanded Compose configuration and validation of the generated Caddy host block;
- bundle verification and restoration into a clean checkout.

**Not proven and blocking cutover:** Docker image build, container operation with
the declared user/filesystem/resource limits, the complete production Caddyfile,
external TLS/CDN behaviour, and the actual old production state/rollback image.
The first staging container must be built and tested by you on a host where you
are authorized to use Docker. A passing host process is not a passing container.

## Operator sequence

1. Read `RELEASE.json`, this handover, and the fetched `DEPLOY.md` and `CLAUDE.md`.
2. Inspect current production: live image/entrypoint, dirty/untracked files,
   commit, Compose project, ports/network and host-specific Caddy configuration.
   Do not print secrets or dump container environment variables.
3. Preserve the old image under a rollback tag and its matching Compose,
   environment and proxy configuration. Keep them outside the working tree with
   operator-only permissions. A rollback is not a Git history rewrite.
4. Review/import the branch separately. If upstream has advanced beyond the
   original `ffe3a58` baseline, reconcile it normally and rerun all tests. The owner
   decides the reviewed merge to `main`; do not force-push or silently discard work.
5. Build the reviewed deployment commit, with `BOMBOMETRO_REVISION` set to its full
   SHA, `PUBLIC_HOST=bombometro.borant.eu`, and the verified host port (8502 expected).
6. Stage the image on an unused loopback test port as described in `DEPLOY.md`.
   Do not start a second production-subnet Compose stack next to the old one.
   Run `python -m deployment.smoke ...`, inspect hardening/health/logs and use the
   browser. **Stop on any failed check before touching the old service.**
7. Confirm that use is non-commercial, with no ads/subscriptions, under the free
   Open-Meteo API terms. No paid key or account has been requested or provisioned.
   If the actual use is commercial, return that licensing decision to the owner.
8. Generate/review the public host block. Replace only the old Bombometro block,
   validate the complete Caddyfile, and preserve unrelated routing/security rules.
   No Borant ID grant is needed for intentionally public access. Ensure CDN rules
   respect `no-store`; do not add analytics/script injection that violates CSP.
9. Confirm/update the backup perimeter: no irreplaceable application state, only
   in-memory reconstructible forecasts. Use the current manifest schema and retain
   old deployment secrets/backups separately; this bundle does not edit that repo.
10. Deploy the tested image under the old Compose project name; verify local and
    external unauthenticated HTTPS routes, live data, revision, browser and logs.
    Roll back using the retained image **and its matching old configuration** if
    acceptance fails. Report the actual deployed commit and checks to the owner.

Keep the workshop preview on lab3 until the owner accepts the public site. Do not
restart unrelated apps, rewrite `main`, delete volumes, prune images or migrate
the stale AI-advisor key into the new container.

## Remaining product limitations

This release does not validate the weather heuristics. Some selectable models
omit pressure-level variables and correctly remain unclassified. Meduno's numeric
thresholds and Innsbruck–Bolzano pressure proxy are not locally calibrated; launch
elevation sources disagree. Permissions, airspace, NOTAMs, Bora and flight safety
remain outside the tool. Those limitations must remain visible after deployment.
