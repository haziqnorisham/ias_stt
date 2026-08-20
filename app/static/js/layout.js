/* Layout behaviour — vanilla JS, no jQuery. */

(function () {
  "use strict";

  // --- Theme toggle (dark is default; preference persisted per browser) ---
  var THEME_KEY = "ias-theme";
  var themeToggle = document.getElementById("themeToggle");

  function currentTheme() {
    return document.documentElement.getAttribute("data-bs-theme") === "light"
      ? "light"
      : "dark";
  }

  function renderThemeIcon() {
    if (!themeToggle) return;
    var icon = themeToggle.querySelector("i");
    if (icon) {
      icon.className = currentTheme() === "dark" ? "bi bi-sun" : "bi bi-moon";
    }
  }

  if (themeToggle) {
    themeToggle.addEventListener("click", function () {
      var next = currentTheme() === "dark" ? "light" : "dark";
      document.documentElement.setAttribute("data-bs-theme", next);
      try {
        localStorage.setItem(THEME_KEY, next);
      } catch (e) {}
      renderThemeIcon();
    });
    renderThemeIcon();
  }

  // --- Sidebar ---
  var toggle = document.getElementById("sidebarToggle");
  if (!toggle) return;

  function closeSidebar() {
    document.body.classList.remove("sidebar-open");
  }

  toggle.addEventListener("click", function () {
    document.body.classList.toggle("sidebar-open");
  });

  // Close the off-canvas sidebar when a nav link inside it is clicked
  // (mobile sizes only; on desktop the sidebar is always visible).
  document.querySelectorAll(".sidebar .nav-link").forEach(function (link) {
    link.addEventListener("click", function () {
      if (window.innerWidth < 992) closeSidebar();
    });
  });

  // Re-open safe state when the viewport returns to desktop size.
  window.addEventListener("resize", function () {
    if (window.innerWidth >= 992) {
      document.body.classList.remove("sidebar-open");
    }
  });

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") closeSidebar();
  });
})();