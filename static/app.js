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
