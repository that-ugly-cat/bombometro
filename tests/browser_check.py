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

WIND_CONTRAST = """() => {
  const cell = document.querySelector('.wind-heat');
  const original = cell.className;
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = 1;
  const ctx = canvas.getContext('2d', {willReadFrequently: true});
  function rgb(css) {
    ctx.clearRect(0,0,1,1); ctx.fillStyle=css; ctx.fillRect(0,0,1,1);
    return Array.from(ctx.getImageData(0,0,1,1).data).slice(0,3);
  }
  function lum(v) {
    return v.map(n=>{n/=255;return n<=.04045?n/12.92:Math.pow((n+.055)/1.055,2.4)})
      .reduce((s,n,i)=>s+n*[.2126,.7152,.0722][i],0);
  }
  const result=[];
  try {
    for(let step=0;step<=30;step++) {
      const range=Math.min(Math.floor(step/10),2);
      cell.className=`wind-heat wind-range-${range} wind-mix-${step-range*10}`;
      const style=getComputedStyle(cell), fg=rgb(style.color), bg=rgb(style.backgroundColor);
      const a=lum(fg),b=lum(bg);
      result.push({step,bg,ratio:(Math.max(a,b)+.05)/(Math.min(a,b)+.05)});
    }
    const style=getComputedStyle(cell);
    return {steps:result,blue:rgb(style.getPropertyValue('--wind-blue')),
      red:rgb(style.getPropertyValue('--wind-red'))};
  } finally { cell.className=original; }
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
    assert page.locator(".wind-table tbody tr").count() == 6
    assert page.locator(".wind-table tbody td").count() == 90
    assert page.locator(".wind-table-card").evaluate("el => el.nextElementSibling.id === 'hourly-details'")
    assert page.locator(".day-card .regime-badge").count() == 5
    assert page.locator(".verdict-face").count() > 0
    report = []
    for theme in ("dark", "light"):
        if page.locator("html").get_attribute("data-theme") != theme:
            page.locator("#theme-toggle").click()
        contrast = page.evaluate(CONTRAST)
        assert all(c["ratio"] >= 4.5 for c in contrast), contrast
        wind_contrast = page.evaluate(WIND_CONTRAST)
        assert min(c["ratio"] for c in wind_contrast["steps"]) >= 4.5, wind_contrast
        assert wind_contrast["steps"][0]["bg"] == wind_contrast["blue"]
        assert wind_contrast["steps"][-1]["bg"] == wind_contrast["red"]
        assert len({tuple(c["bg"]) for c in wind_contrast["steps"]}) == 31
        for width in (1440, 768, 390, 320):
            page.set_viewport_size({"width": width, "height": 1000})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (theme, width)
            for index in (9, 10):
                assert page.locator(".chart-card").nth(index).locator(".y-label").evaluate_all("""els => els.every(el => {
                    const label=el.getBoundingClientRect(),svg=el.ownerSVGElement.getBoundingClientRect();
                    return label.left>=svg.left && label.right<=svg.right;
                })"""), (theme, width, index)
            assert page.locator(".chart-card").nth(9).locator(".right-axis").count() == 5
            assert page.locator(".chart-card").nth(9).locator(".secondary-line").count() > 0
            page.screenshot(path=str(OUTPUT / f"forecast-{theme}-{width}.png"), full_page=True)
            if width in (1440, 320):
                for i in range(12):
                    card = page.locator(".chart-card").nth(i)
                    svg = card.locator(".chart")
                    svg.scroll_into_view_if_needed()
                    page.mouse.move(0, 0)
                    box = svg.bounding_box()
                    payload = json.loads(card.locator(".chart-hover-data").text_content())
                    expected = payload["hours"][5]
                    page.mouse.move(box["x"] + box["width"] * expected["x"] / 752,
                                    box["y"] + box["height"] * 70 / 185)
                    tip = card.locator(".chart-tooltip")
                    assert tip.is_visible(), (theme, width, i)
                    assert tip.locator(".tooltip-heading").inner_text().startswith("11:00")
                    assert tip.locator(".tooltip-row b").all_text_contents() == [r["value"] for r in expected["readings"]]
                    assert tip.locator(".tooltip-regime").inner_text() == "Thermal regime: " + expected["regime"]
                    bounds = tip.bounding_box()
                    assert bounds["x"] >= 0 and bounds["x"] + bounds["width"] <= width
                    svg.focus()
                    svg.press("Home")
                    svg.press("ArrowRight")
                    assert tip.locator(".tooltip-heading").inner_text().startswith("07:00")
                    svg.press("End")
                    assert tip.locator(".tooltip-heading").inner_text().startswith("20:00")
                    svg.press("Escape")
                    assert not tip.is_visible()
                    svg.evaluate("el => el.blur()")
                table = page.locator(".table-wrap")
                table.evaluate("el => el.scrollLeft = el.scrollWidth")
                assert table.evaluate("el => el.scrollLeft > 0")
                table.evaluate("el => el.scrollLeft = 0")
        report.append({"theme": theme, "contrast": contrast, "wind_contrast": wind_contrast})
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
    touch_context = browser.new_context(viewport={"width": 390, "height": 844},
                                        is_mobile=True, has_touch=True)
    touch = touch_context.new_page()
    touch.on("pageerror", lambda error: errors.append(str(error)))
    touch.goto(BASE + "/app", wait_until="networkidle")
    wind_card = touch.locator(".chart-card").nth(2)
    wind_svg = wind_card.locator(".chart")
    wind_svg.scroll_into_view_if_needed()
    box = wind_svg.bounding_box()
    wind_payload = json.loads(wind_card.locator(".chart-hover-data").text_content())
    touch.touchscreen.tap(box["x"] + box["width"] * wind_payload["hours"][6]["x"] / 752,
                          box["y"] + box["height"] * 70 / 185)
    assert wind_card.locator(".chart-tooltip").is_visible()
    assert wind_card.locator(".tooltip-heading").inner_text().startswith("12:00")
    touch.screenshot(path=str(OUTPUT / "wind-tooltip-touch.png"))
    touch.locator(".chart-help").tap()
    assert not wind_card.locator(".chart-tooltip").is_visible()
    assert not errors, errors
    touch_context.close()
    browser.close()
    (OUTPUT / "browser-results.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"browser": "Chromium", "themes": 2, "widths": [1440, 768, 390, 320],
                      "console_errors": errors, "contrast": report}, indent=2))
