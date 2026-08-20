/* SB Admin 2-style layout behaviour — vanilla JS, no jQuery. */

(function () {
  "use strict";

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