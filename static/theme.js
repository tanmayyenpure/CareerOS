/* =====================================================================
   CareerOS — shared theme.js
   Include this on EVERY page, in <head>, BEFORE any <style> block or
   other CSS, and WITHOUT defer/async. That way it runs and sets the
   data-theme attribute before the page paints — no flash of the
   wrong theme.

   Public API (unchanged):
   - window.setTheme('light' | 'dark')
   - window.getTheme() -> 'light' | 'dark'
   - "storage" event keeps other open tabs in sync live.
   ===================================================================== */
(function () {
  "use strict";

  var STORAGE_KEY = "careeros-theme";
  var root = document.documentElement;

  function getSavedTheme() {
    try {
      return localStorage.getItem(STORAGE_KEY) || "dark";
    } catch (e) {
      return "dark"; // localStorage unavailable (e.g. private mode) -> default
    }
  }

  function applyTheme(theme) {
    root.setAttribute("data-theme", theme);
  }

  // Apply immediately, synchronously, before body renders.
  applyTheme(getSavedTheme());

  // Global function pages call to change theme (e.g. settings toggle).
  window.setTheme = function (theme) {
    if (theme !== "light" && theme !== "dark") return;
    applyTheme(theme);
    try {
      localStorage.setItem(STORAGE_KEY, theme);
    } catch (e) {
      /* ignore write failures (private mode / storage disabled) */
    }
  };

  // Helper for pages that want to read current theme.
  window.getTheme = getSavedTheme;

  // Keep other open tabs/pages in sync if the user toggles elsewhere.
  window.addEventListener("storage", function (e) {
    if (e.key === STORAGE_KEY && e.newValue) {
      applyTheme(e.newValue);
    }
  });
})();
