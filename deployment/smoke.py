"""Read-only deployment acceptance checks, including actual weather availability."""

import argparse
import json
import re
import urllib.request
from urllib.parse import urlsplit


def check_forecast_data(page):
    """A rendered chart is not evidence of available weather inputs."""
    match = re.search(r'<script type="application/json" id="forecast-availability">(.*?)</script>', page, re.S)
    assert match, "Missing forecast availability metadata"
    data = json.loads(match.group(1))
    total, complete = data["total_hours"], data["complete_hours"]
    assert type(total) is int and type(complete) is int and 15 <= complete <= total, data
    assert any(type(count) is int and count == 15 for count in data["daytime_complete_hours"]), data
    return data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("base", help="Loopback candidate URL or public HTTPS URL")
    parser.add_argument("--revision", required=True)
    parser.add_argument("--host-header", help="Public hostname when probing a loopback port")
    args = parser.parse_args()
    base = args.base.rstrip("/")
    if urlsplit(base).scheme not in {"http", "https"}:
        parser.error("Use an HTTP(S) base URL")
    if not re.fullmatch(r"[0-9a-f]{40}", args.revision):
        parser.error("Use the full reviewed commit")

    def get(path):
        headers = {"User-Agent": "Bombometro-deployment-check/1"}
        if args.host_header:
            headers["Host"] = args.host_header
        request = urllib.request.Request(base + path, headers=headers)
        with urllib.request.urlopen(request, timeout=65) as response:
            assert response.status == 200, path
            assert response.geturl() == base + path, "Unexpected redirect (possibly authentication)"
            assert response.headers.get("Cache-Control") == "no-store", path
            assert response.headers.get("X-Content-Type-Options") == "nosniff", path
            return response.read().decode()

    health = json.loads(get("/healthz"))
    assert health == {"status": "ok", "service": "bombometro", "mode": "public", "revision": args.revision}, health
    home = get("/")
    assert "PUBLIC / BETA" in home and "3 flying sites" in home
    get("/guide")
    for site in ("Grappa", "Cavallaria", "Meduno"):
        page = get(f"/app?site={site}&model=icon_eu")
        assert page.count('class="card chart-card"') == 12, site
        assert 'class="table wind-table"' in page, site
        assert 'class="day-grid"' in page, site
        available = check_forecast_data(page)
        print(f"{site}: {available['complete_hours']}/{available['total_hours']} complete source hours; "
              f"daytime counts {available['daytime_complete_hours']}")
        if site == "Meduno":
            assert "not locally calibrated" in page and "225° ± 45°" in page
    assets = re.findall(r'(?:src|href)="(/static/[^"#]+)"', home)
    assert assets
    for asset in assets:
        get(asset)
    assert "Disallow: /" in get("/robots.txt")
    print(f"PASS: public routes, live ICON EU forecasts, assets and revision {args.revision}")
    print("Still required: browser interaction, container logs and real external TLS checks.")


if __name__ == "__main__":
    main()
