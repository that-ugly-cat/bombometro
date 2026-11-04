# Workshop operation

This is a loopback-only preview behind an existing authenticated reverse proxy.
It has no standalone authentication and no Borant ID integration. Do not turn the
preview into a public service by simply changing the bind address.

## Start

From the project directory:

```sh
uv sync --frozen --no-dev
setsid nohup .venv/bin/uvicorn web:app --host 127.0.0.1 --port 8103 --no-access-log \
  > servizio.log 2>&1 < /dev/null &
```

Use one worker: cache and locks are process-local. Check the port before launch
and identify its owner; do not kill an unknown listener. The lab's old preview was
stopped explicitly before this service was started. No system service or reboot
autostart is installed. A machine reboot requires starting the preview again.

## Verify

```sh
ss -ltnp '( sport = :8103 )'
curl --fail http://127.0.0.1:8103/healthz
curl --fail http://127.0.0.1:8103/app
```

Also check the rendered browser page and the application log. The health endpoint
only checks the application process, not upstream forecast availability. Verify
that unauthenticated requests through the external proxy are rejected, and check
the authenticated browser path separately. Never copy login cookies into tests.

The application sets `Cache-Control: no-store` on all responses, including static
assets. Asset URLs also carry a content hash. There are no external scripts or
fonts. The inline head script restores the colour theme before first paint.

## Stop / restart

Find the exact preview PID with `ss`, verify its command and working directory,
and send `SIGTERM` to that PID. Wait for the port to be released, then start the
new process. The only state lost is the reconstructible forecast cache.

## Before any production proposal

- Decide standalone versus gateway authentication and access policy.
- Add the appropriate container recipe and generated proxy configuration; the
  existing upstream compose file is for the old Streamlit deployment, not this UI.
- Declare the application state as empty, with its reason, in the backup perimeter.
- Resolve model coverage and score validation requirements with the owner.
- Review the legacy manual and any future AI advisor separately.
- Do not infer permission to deploy from a successful lab preview.

Ono · dedalo · gpt-6-astra-fast
