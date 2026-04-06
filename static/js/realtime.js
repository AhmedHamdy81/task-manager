(function () {
  "use strict";

  function toast(text, opts) {
    var host = document.getElementById("realtime-toast-host");
    if (!host || !text) return;
    var el = document.createElement("div");
    el.className = "realtime-toast";
    el.setAttribute("role", "status");
    if (opts && opts.href) {
      var a = document.createElement("a");
      a.href = opts.href;
      a.className = "realtime-toast-link";
      a.textContent = text;
      el.appendChild(a);
    } else {
      el.textContent = text;
    }
    host.appendChild(el);
    window.setTimeout(function () {
      el.classList.add("realtime-toast--out");
      window.setTimeout(function () {
        if (el.parentNode) el.parentNode.removeChild(el);
      }, 280);
    }, 7000);
  }

  document.addEventListener("DOMContentLoaded", function () {
    if (typeof io === "undefined") return;

    var host = document.getElementById("realtime-toast-host");
    var token = host && host.getAttribute("data-socket-token");
    var opts = {
      path: "/socket.io",
      withCredentials: true,
    };
    if (token) opts.auth = { token: token };
    var socket = io(opts);
    window.__tmSocket = socket;

    socket.on("notification", function (data) {
      if (!data || typeof data !== "object") return;
      if (data.type === "task_assigned") {
        var title = data.title || "New task";
        var proj = data.project_name ? " · " + data.project_name : "";
        toast(title + proj, { href: data.href || "/tasks" });
      } else if (data.type === "mention") {
        toast(data.message || "You were mentioned", data.href ? { href: data.href } : null);
      } else {
        toast(data.message || "New notification", data.href ? { href: data.href } : null);
      }
    });

    socket.on("connect_error", function () {
      /* WebSocket-only: stay quiet; user still has the rest of the app. */
    });
  });
})();
