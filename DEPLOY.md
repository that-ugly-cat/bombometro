# Public deployment and rollback

Owner decision, 5 November 2026: anonymous public access, without Borant ID.
This is a read-only weather explorer, not a validated flight-safety service.

**Preparation is not deployment.** The workshop shell cannot access the Docker
daemon. Compose expansion, Caddy validation, application tests and an isolated
public-mode process can be tested there; the image build and container runtime
must pass on the deployment host before changing the live service.

## Runtime contract

- Python 3.11, dependencies from `uv.lock`, one uvicorn worker.
- `APP_MODE=lab` by default. Public mode requires `PUBLIC_HOST` (DNS hostname only)
  and `APP_REVISION` (full reviewed Git commit). Health reports both mode and revision.
- All application paths are anonymous, including `/app`. No login, cookies,
  accounts, Borant headers, paid API keys, AI advisor, database or writable volume.
- Container listens on 8502 internally; **only 127.0.0.1 is published on the host**.
  Caddy terminates public TLS. Never change the host bind to `0.0.0.0`.
- Non-root UID/GID 10001, read-only root, 16 MB temporary filesystem, no Linux
  capabilities, no-new-privileges, 384 MB RAM, one CPU, 64 PIDs.
- Source and dependency files are copied explicitly. `.dockerignore` is an
  allowlist; old `.env`, Git history, caches, tests and Streamlit/AI files stay out.
- No access logs from uvicorn. Container lifecycle/error logs rotate at 2 × 5 MB.
  Inspect the existing proxy/CDN logging policy separately; this app cannot change it.
- Cache and rate budgets are in memory and reset on restart. No irreplaceable
  application state. Add/confirm a **declares-no-state** backup perimeter entry
  with this reason, using the current backup manifest schema. Do not remove old
  deployment backups or its `.env` during this migration.

## Provider terms and capacity

The free Open-Meteo API is for non-commercial operation: no advertisements,
subscriptions or promotional/commercial use. Public access alone does not make
the app commercial. Confirm the deployment's actual use before launch; a commercial
use requires a separate licensed endpoint decision, not an unannounced paid call.
Terms checked 5 November 2026: https://open-meteo.com/en/terms.

The app has 15 fixed site/model cache keys, each valid for 30 minutes; date and
arbitrary query parameters cannot create more keys. It admits at most four public
forecast requests concurrently, with a shared burst of 20 and refill of one per
second. No visitor/IP identifiers are stored. Cache fetches are limited to two
concurrently; same-key waiters time out after two seconds. Health is asynchronous
and does not queue behind blocking forecast workers.

Upstream transport calls are capped per process at 30/minute, 300/hour and 2,000/day;
provider rate-limit/budget failures back off for five minutes, other failures for
one minute. These count HTTP requests, **not Open-Meteo's weighted billing units**.
Other apps sharing the host IP consume the provider quota too. This is bounded
admission for a modest site, not DDoS protection or a guarantee of upstream service.
Retain existing edge protection if needed; do not silently cache dynamic HTML.

## 1. Inspect and preserve the current deployment

Before touching the live checkout, determine its repository status, branch,
actual image/entrypoint, compose project, host port, network and proxy block.
Do not infer these from a Git log. Stop if the checkout is dirty or has untracked
deployment files that the new commit would replace; reconcile them with the owner.

Preserve, outside the checkout and with operator-only permissions:

- current commit and container image ID;
- a retained tag for the running image, e.g. `bombometro:rollback-<timestamp>`;
- the old Dockerfile/Compose and proxy configuration;
- the old environment file, **without printing its values or putting it in Git**.

Use targeted `docker inspect --format` queries such as `{{.Image}}`, not a full
inspect dump containing environment values. Record the old compose project name.
Do not prune images, delete volumes or run a broad service restart.

## 2. Review and build in a separate checkout

Import the supplied Git bundle in a review clone, not over the live checkout:

```sh
git bundle verify /path/to/bombometro.bundle
git fetch /path/to/bombometro.bundle refs/heads/dedalo/borant-lab:refs/remotes/dedalo/borant-lab
git switch -c review/bombometro-public refs/remotes/dedalo/borant-lab
uv sync --frozen
uv run pytest -q
```

Publish/review the branch through the owner's usual Git workflow. The owner's
reviewed merge decides what goes on `main`; this bundle does not authorize a force
push or rewritten history. Build the exact commit that will be deployed:

```sh
export PUBLIC_HOST=bombometro.example.org  # Set the actual public hostname.
export BOMBOMETRO_REVISION="$(git rev-parse HEAD)"
export BOMBOMETRO_PORT=8502
docker compose config --quiet
docker compose build --pull
```

`uv` is pinned to 0.12.24 in the builder; Python's 3.11 slim tag receives security
updates. Record the resolved base/image IDs. Runtime dependency versions/hashes are
locked, but this is not a claim that future base-image builds are byte-identical.

**Stop if build fails.** Do not fix failure by reverting to the old Streamlit
requirements, copying the whole checkout, injecting an AI key or running as root.

## 3. Run the candidate without disturbing Streamlit

Choose a free loopback-only test port; 18502 below is an example, not a reservation.
Do not start a second copy of the production Compose subnet: it is intentionally
pinned to the legacy `10.200.123.0/24`. Use the default bridge for the candidate:

```sh
docker run -d --name bombometro-candidate \
  --publish 127.0.0.1:18502:8502 \
  --read-only --tmpfs /tmp:rw,noexec,nosuid,size=16m,mode=1777 \
  --cap-drop ALL --security-opt no-new-privileges:true \
  --memory 384m --cpus 1 --pids-limit 64 \
  --env APP_MODE=public --env PUBLIC_HOST="$PUBLIC_HOST" \
  --env APP_REVISION="$BOMBOMETRO_REVISION" \
  "bombometro:$BOMBOMETRO_REVISION"
python -m deployment.smoke http://127.0.0.1:18502 \
  --host-header "$PUBLIC_HOST" --revision "$BOMBOMETRO_REVISION"
docker logs --tail 100 bombometro-candidate
```

Inspect the candidate's configured user, read-only filesystem, published bind,
resource limits, health and image revision label. Check that `/app/.env`,
`/app/.git`, `/app/advisor.py` and `/app/bombometro_app_v2.py` do not exist in it.
Test the browser through an operator-controlled tunnel or existing private test
route: theme persistence, sites/dates, regime popovers, plot tooltips and the wind
table. No public candidate hostname is required.

**Image/container verification is mandatory and was not performed by Dedalo.**
Remove only the candidate when done: `docker rm -f bombometro-candidate`.

## 4. Configure the public proxy and cut over

Generate a replacement block for the real hostname and actual host port:

```sh
python -m deployment.caddy --host "$PUBLIC_HOST" --port "$BOMBOMETRO_PORT"
```

The generated block has **no `forward_auth`**. It strips identity/authorization
headers upstream; the app does not trust proxy identity headers anyway. Replace
only the old Bombometro block, not the entire Caddyfile. Validate the **complete**
resulting configuration with the host's Caddy command before reloading it.

Keep DNS, TLS/Cloudflare routing, the host port and the pinned network unchanged
unless inspection proves a change is necessary. No Borant ID app/grant is needed
for this deliberately public app. If an old gate registration exists, resolve it
explicitly instead of changing shared gate rules. Check that the CDN does not
override `no-store` or inject scripts blocked by CSP.

After the reviewed merge, update the live checkout with a normal fast-forward;
deploy the already tested image with the **existing compose project name**:

```sh
docker compose -p EXISTING_PROJECT up -d --no-build
```

This restarts only Bombometro. Set the same hostname, revision and port variables
used for the tested image. Reload Caddy only if its validated block changed.

## 5. Acceptance and rollback

Run the smoke check locally and on the actual HTTPS URL without login/cookies:

```sh
python -m deployment.smoke "https://$PUBLIC_HOST" --revision "$BOMBOMETRO_REVISION"
```

Verify container health/logs and actual browser interactions. `/healthz` checks the
process; the smoke command also requires at least 15 complete source hours and
one fully complete 06:00–20:00 day of ICON EU inputs for each of the three sites.
Complete inputs do not mean flyable conditions: an all-veto day can still pass
this data-availability check. A rendered empty chart alone cannot pass it.
Other models can legitimately have incomplete scoring inputs. Meduno remains an
explicitly experimental preset with inherited numeric limits and pressure proxy.

If acceptance fails, restore the previous **retained image plus its matching
Compose/environment** and the old proxy block. The old service may have used a
different entrypoint, user or environment: changing only the image name in the
new Compose is not a reliable rollback. Recreate it under the recorded old project
name, validate/reload the restored proxy only if necessary, and verify the old
Streamlit page and logs. Do not reset Git history or discard local files to roll
back. There is no application-data migration to undo.

Keep lab3 running until the owner accepts the public site. Stop the preview only
after that confirmation; it is on a different machine from the production service.

Ono · dedalo · gpt-6-astra-fast
