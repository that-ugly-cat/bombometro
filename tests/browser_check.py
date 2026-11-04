"""Live preview smoke test. Run explicitly; requires a local preview and Chromium."""

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8103"
OUTPUT = Path(__file__).resolve().parents[1] / "runtime"
OUTPUT.mkdir(exist_ok=True)

# Calculate contrast from computed DOM styles, walking to the first opaque ancestor.
CONTRAST = """() => {
  function rgb(value) { return (value.match(/[\\d.]+/g) || []).map(Number); }
  function luminance(v) {
    return v.slice(0,3).map(n => {n/=255;return n<=.04045?n/12.92:Math.pow((n+.055)/1.055,2.4)})
      .reduce((s,n,i)=>s+n*[.2126,.7152,.0722][i],0);
  }
  const result = [];
  for (const selector of ['h1', '.eyebrow', '.day-date', '.day-window', '.day-card strong',
      '.verdict', '.summary-copy', '.hour.blocked', '.hour.marginal', '.hour.promising',
      '.chart-note', '.legend', '.btn-primary', '.control-note', '.provenance', '.unit']) {
    const el = document.querySelector(selector);
    if (!el) continue;
    let parent=el, background;
    while(parent) {
      const c=rgb(getComputedStyle(parent).backgroundColor);
      if(c.length===3 || c[3]===1) {background=c;break;}
      parent=parent.parentElement;
    }
    if(!background) throw new Error('No opaque background: '+selector);
    const foreground=rgb(getComputedStyle(el).color);
    const a=luminance(foreground),b=luminance(background);
    const ratio=(Math.max(a,b)+.05)/(Math.min(a,b)+.05);
    result.push({selector,ratio:Math.round(ratio*100)/100});
  }
  return result;
}"""

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    response = page.goto(BASE + "/app", wait_until="networkidle", timeout=90000)
    assert response.status == 200, page.locator(".flash").inner_text()
    assert page.locator(".day-card").count() == 5
    assert page.locator(".chart-card").count() == 12
    report = []
    for theme in ("dark", "light"):
        if page.locator("html").get_attribute("data-theme") != theme:
            page.locator("#theme-toggle").click()
        contrast = page.evaluate(CONTRAST)
        assert all(c["ratio"] >= 4.5 for c in contrast), contrast
        for width in (1440, 768, 390, 320):
            page.set_viewport_size({"width": width, "height": 1000})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (theme, width)
            page.screenshot(path=str(OUTPUT / f"forecast-{theme}-{width}.png"), full_page=True)
        report.append({"theme": theme, "contrast": contrast})
    page.reload(wait_until="networkidle")
    assert page.locator("html").get_attribute("data-theme") == "light"
    page.locator(".hour").nth(6).click()
    assert page.locator("#hour-12").get_attribute("open") is not None
    assert page.locator("#hour-12 .raw-grid").is_visible()
    day = page.locator(".day-card").nth(1)
    target = day.get_attribute("href")
    day.click()
    page.wait_for_url(BASE + target, wait_until="networkidle")
    assert page.locator(".day-card.selected").get_attribute("href") == target
    page.select_option('select[name="site"]', "Cavallaria")
    page.locator('button[type="submit"]').click()
    page.wait_for_url("**/app?site=Cavallaria&model=icon_eu", wait_until="networkidle", timeout=90000)
    assert "CAVALLARIA" in page.locator(".day-overview").inner_text()
    assert "Grappa /" not in page.locator(".configuration").inner_text()
    page.goto(BASE + "/guide", wait_until="networkidle")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.goto(BASE + "/", wait_until="networkidle")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert not errors, errors
    browser.close()
    (OUTPUT / "browser-results.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"browser": "Chromium", "themes": 2, "widths": [1440, 768, 390, 320],
                      "console_errors": errors, "contrast": report}, indent=2))
