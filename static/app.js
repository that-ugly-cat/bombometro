"use strict";

const themeButton = document.getElementById("theme-toggle");
function themeLabel() {
  const light = document.documentElement.dataset.theme === "light";
  themeButton.textContent = light ? "Dark mode" : "Light mode";
  themeButton.setAttribute("aria-label", light ? "Switch to dark mode" : "Switch to light mode");
}
themeLabel();
themeButton.addEventListener("click", () => {
  const theme = document.documentElement.dataset.theme === "light" ? "dark" : "light";
  document.documentElement.dataset.theme = theme;
  try { localStorage.setItem("bombometro-theme", theme); } catch (_) { /* Session-only theme. */ }
  themeLabel();
});

function openHour() {
  if (!/^#hour-\d{2}$/.test(location.hash)) return;
  const target = document.getElementById(location.hash.slice(1));
  if (target) {
    target.open = true;
    target.querySelector("summary").focus({ preventScroll: true });
    target.scrollIntoView({ block: "start" });
  }
}
window.addEventListener("hashchange", openHour);
openHour();
document.querySelectorAll('.hour[href^="#hour-"]').forEach(link => {
  link.addEventListener("click", () => {
    const target = document.getElementById(link.hash.slice(1));
    if (target) target.open = true;
  });
});
const form = document.getElementById("forecast-form");
if (form) form.addEventListener("submit", () => {
  const button = form.querySelector('button[type="submit"]');
  button.disabled = true;
  button.textContent = "Loading…";
  document.getElementById("load-status").textContent = "Fetching forecast and reference pressures…";
});
window.addEventListener("pageshow", () => {
  if (!form) return;
  const button = form.querySelector('button[type="submit"]');
  button.disabled = false;
  button.textContent = "Load forecast →";
  document.getElementById("load-status").textContent = "Up to 5 days · cached for 30 min";
});

// Unified per-hour tooltips: values come from the same arrays as the SVG lines.
let dismissActiveChart = null;
document.querySelectorAll(".chart-card").forEach(card => {
  const svg = card.querySelector(".chart");
  const container = card.querySelector(".chart-interaction");
  const tooltip = card.querySelector(".chart-tooltip");
  const crosshair = card.querySelector(".chart-crosshair");
  const announcement = card.querySelector(".chart-announcement");
  const data = JSON.parse(card.querySelector(".chart-hover-data").textContent);
  if (!data.hours.length) return;
  let index = 0;

  function hide() {
    tooltip.hidden = true;
    crosshair.setAttribute("visibility", "hidden");
    announcement.textContent = "";
    if (dismissActiveChart === hide) dismissActiveChart = null;
  }
  function show(next, announce = false) {
    if (dismissActiveChart && dismissActiveChart !== hide) dismissActiveChart();
    dismissActiveChart = hide;
    index = Math.max(0, Math.min(data.hours.length - 1, next));
    const hour = data.hours[index];
    const heading = document.createElement("strong");
    heading.className = "tooltip-heading";
    heading.textContent = `${hour.time} · ${data.secondary ? 'local time' : data.unit}`;
    tooltip.replaceChildren(heading);
    for (const reading of hour.readings) {
      const row = document.createElement("div");
      row.className = "tooltip-row";
      const label = document.createElement("span");
      const swatch = document.createElement("i");
      swatch.className = `swatch c${reading.color}`;
      swatch.setAttribute("aria-hidden", "true");
      label.append(swatch, document.createTextNode(reading.label));
      const value = document.createElement("b");
      value.textContent = reading.value;
      row.append(label, value);
      tooltip.append(row);
    }
    if (hour.status) {
      const status = document.createElement("p");
      status.className = "tooltip-status";
      status.textContent = hour.status;
      tooltip.append(status);
    }
    const regime = document.createElement("p");
    regime.className = "tooltip-regime";
    regime.textContent = `Thermal regime: ${hour.regime}`;
    tooltip.append(regime);
    tooltip.hidden = false;
    crosshair.setAttribute("x1", hour.x);
    crosshair.setAttribute("x2", hour.x);
    crosshair.setAttribute("visibility", "visible");
    // Keep the box inside the card at all viewport widths, away from the pointer.
    const width = container.clientWidth;
    const x = hour.x / 752 * width;
    const preferred = x < width / 2 ? x + 14 : x - tooltip.offsetWidth - 14;
    tooltip.style.left = `${Math.max(0, Math.min(width - tooltip.offsetWidth, preferred))}px`;
    if (announce) announcement.textContent = `${hour.time}. ${hour.readings.map(r => `${r.label}: ${r.value}${data.secondary ? '' : ' ' + r.unit}`).join('. ')}. ${hour.status}. Thermal regime: ${hour.regime}`;
  }
  function point(event) {
    const matrix = svg.getScreenCTM();
    if (!matrix) return;
    const position = new DOMPoint(event.clientX, event.clientY).matrixTransform(matrix.inverse());
    if (position.x < data.left - 12 || position.x > data.right + 12 || position.y < 15 || position.y > 165) {
      if (!tooltip.contains(event.target)) hide();
      return;
    }
    const next = Math.round((position.x - data.left) / (data.right - data.left) * (data.hours.length - 1));
    if (tooltip.hidden || next !== index) show(next);
  }
  container.addEventListener("pointermove", event => {
    if (event.pointerType !== "touch") point(event);
  });
  container.addEventListener("pointerup", point);
  svg.addEventListener("focus", () => show(index, true));
  svg.addEventListener("blur", hide);
  card.addEventListener("pointerleave", event => {
    if (event.pointerType !== "touch") hide();
  });
  svg.addEventListener("keydown", event => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End", "Escape"].includes(event.key)) return;
    event.preventDefault();
    if (event.key === "Escape") return hide();
    show(event.key === "Home" ? 0 : event.key === "End" ? data.hours.length - 1 :
      index + (event.key === "ArrowRight" ? 1 : -1), true);
  });
});
document.addEventListener("keydown", event => {
  if (event.key === "Escape" && dismissActiveChart) dismissActiveChart();
});
document.addEventListener("pointerdown", event => {
  if (!event.target.closest(".chart-card") && dismissActiveChart) dismissActiveChart();
});
window.addEventListener("resize", () => { if (dismissActiveChart) dismissActiveChart(); });
