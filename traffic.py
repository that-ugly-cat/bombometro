"""Bounded public request admission, with no IP address or visitor tracking."""

from threading import Lock
from time import monotonic

from starlette.responses import HTMLResponse


class Admission:
    def __init__(self, burst=20, per_second=1, concurrent=4, clock=monotonic):
        self.burst = burst
        self.rate = per_second
        self.concurrent = concurrent
        self.clock = clock
        self.tokens = float(burst)
        self.last = clock()
        self.active = 0
        self.lock = Lock()

    def enter(self):
        with self.lock:
            now = self.clock()
            self.tokens = min(self.burst, self.tokens + (now - self.last) * self.rate)
            self.last = now
            if self.active >= self.concurrent:
                return 503
            if self.tokens < 1:
                return 429
            self.tokens -= 1
            self.active += 1
            return None

    def leave(self):
        with self.lock:
            self.active -= 1


class PublicGuard:
    """Global budget, not per-IP: forwarded headers cannot mint fresh identities."""

    def __init__(self, app, admission=None):
        self.app = app
        self.admission = admission or Admission()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        status, message = None, None
        headers = {}
        if len(scope.get("raw_path", b"")) + len(scope.get("query_string", b"")) > 2048:
            status, message = 414, "The request URL is too long."
        elif scope["method"] not in {"GET", "HEAD"}:
            status, message = 405, "This is a read-only forecast service."
            headers["Allow"] = "GET, HEAD"
        admitted = False
        if status is None and scope["path"].rstrip("/") == "/app":
            status = self.admission.enter()
            admitted = status is None
            if status:
                message = "The forecast service is busy. Please try again shortly."
                headers["Retry-After"] = "2" if status == 503 else "1"
        if status:
            response = HTMLResponse(
                f'<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" '
                f'content="width=device-width,initial-scale=1"><title>Bombometro</title>'
                f'<h1>Request unavailable</h1><p>{message}</p><a href="/app">Back to forecasts</a></html>',
                status_code=status, headers=headers)
            return await response(scope, receive, send)
        try:
            await self.app(scope, receive, send)
        finally:
            if admitted:
                self.admission.leave()
