"""Lab-only web presentation. No credentials, accounts or paid model calls."""

import hashlib
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from charts import day_charts, wind_table, regime_label
from regimes import REGIMES, regime_info
from site_details import SITE_DETAILS
from core import HOURLY_VARS, SITE_PRESETS, get_sun_times, wind_dir_label
from forecast import MODELS, ForecastCache, ForecastError, make_site

ROOT = Path(__file__).parent
app = FastAPI(title="Bombometro lab", docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
templates = Jinja2Templates(directory=ROOT / "templates")
cache = ForecastCache()
ASSET_VERSION = hashlib.sha256(b"".join(
    p.read_bytes() for p in sorted((ROOT / "static").glob("*")) if p.is_file()
)).hexdigest()[:12]
ERRORS = {
    "unreachable": "Open-Meteo could not be reached. No substitute data is shown. Try again in a minute.",
    "provider_error": "Open-Meteo rejected this request. The selected model may not cover this site or these variables. Try another model.",
    "rate_limited": "Open-Meteo's request limit was reached. Please wait before trying again.",
    "invalid_data": "The weather response could not be verified. No score has been calculated.",
    "invalid_selection": "Choose one of the available sites and models.",
    "invalid_day": "That date is outside the returned forecast. Choose a day shown below.",
}


def fmt(value, digits=1):
    return "—" if value is None else f"{value:.{digits}f}"


def tone(verdict):
    return {"bad idea": "danger", "if you must": "warning", "meh": "warning",
            "not bad": "good", "hammer day": "good"}.get(verdict, "muted")


templates.env.filters.update(fmt=fmt)
templates.env.globals.update(asset_version=ASSET_VERSION, tone=tone,
                             wind_dir_label=wind_dir_label, regime_label=regime_label,
                             regime_info=regime_info, regimes=REGIMES, site_details=SITE_DETAILS)


@app.middleware("http")
async def private_preview(request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self'; "
        "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
        "base-uri 'self'; form-action 'self'"
    )
    return response


def render(request, name, status=200, **context):
    return templates.TemplateResponse(request=request, name=name,
                                      context=context, status_code=status)


@app.exception_handler(RequestValidationError)
async def invalid_request(request, exc):
    return render(request, "error.html", status=422, message="Invalid forecast request.")


@app.get("/healthz")
def health():
    return {"status": "ok", "service": "bombometro", "mode": "lab"}


@app.get("/", response_class=HTMLResponse)
def landing(request: Request):
    return render(request, "landing.html", site_count=len(SITE_PRESETS))


@app.get("/guide", response_class=HTMLResponse)
def guide(request: Request):
    return render(request, "guide.html")


@app.get("/app", response_class=HTMLResponse)
def workspace(request: Request, site: str = Query("Grappa", max_length=40),
              model: str = Query("icon_eu", max_length=60),
              day: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$")):
    if site not in SITE_PRESETS or model not in MODELS:
        return render(request, "error.html", status=422, message=ERRORS["invalid_selection"])
    config = make_site(site, model)
    context = dict(sites=SITE_PRESETS, models=MODELS, site=config, report=None,
                   error=None, selected_day=day, site_info=SITE_DETAILS.get(site))
    try:
        report = cache.get(config)
    except ForecastError as exc:
        return render(request, "app.html", status=503, **{
            **context, "error": ERRORS.get(str(exc), ERRORS["invalid_data"])})
    selected = day if day in report["days"] else report["days"][0]
    hours = [h for h in report["hours"] if h["time"].startswith(selected)
             and 6 <= int(h["time"][11:13]) <= 20]
    try:
        sun = get_sun_times(config.latitude, config.longitude, config.timezone, selected)
    except ValueError:
        sun = None
    context.update(report=report, selected_day=selected, hours=hours, wind_rows=wind_table(hours, config),
                   summary=report["summaries"][selected], sun=sun,
                   fetched=report["fetched_at"].astimezone(ZoneInfo(config.timezone)),
                   charts=day_charts(hours), raw_keys=HOURLY_VARS + [
                       "pressure_foehn_north", "pressure_foehn_south", "delta_p_foehn"],
                   error=ERRORS["invalid_day"] if day and day not in report["days"] else None)
    return render(request, "app.html", status=422 if context["error"] else 200, **context)
