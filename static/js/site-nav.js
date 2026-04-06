(function () {
  "use strict";

  document.addEventListener("DOMContentLoaded", function () {
    var toggle = document.getElementById("site-nav-toggle");
    var nav = document.getElementById("site-main-nav");
    var backdrop = document.getElementById("site-nav-backdrop");
    if (!toggle || !nav) return;

    var mq = window.matchMedia("(max-width: 900px)");

    function setOpen(open) {
      document.body.classList.toggle("site-nav-open", open);
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
      toggle.setAttribute("aria-label", open ? "Close menu" : "Open menu");
      if (backdrop) {
        if (open) {
          backdrop.removeAttribute("hidden");
          backdrop.setAttribute("aria-hidden", "false");
        } else {
          backdrop.setAttribute("hidden", "");
          backdrop.setAttribute("aria-hidden", "true");
        }
      }
    }

    function closeNav() {
      setOpen(false);
    }

    toggle.addEventListener("click", function () {
      setOpen(!document.body.classList.contains("site-nav-open"));
    });

    if (backdrop) {
      backdrop.addEventListener("click", closeNav);
    }

    nav.querySelectorAll("a").forEach(function (a) {
      a.addEventListener("click", function () {
        if (mq.matches) closeNav();
      });
    });

    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") closeNav();
    });

    if (mq.addEventListener) {
      mq.addEventListener("change", function () {
        if (!mq.matches) closeNav();
      });
    } else if (mq.addListener) {
      mq.addListener(function () {
        if (!mq.matches) closeNav();
      });
    }
  });
})();
