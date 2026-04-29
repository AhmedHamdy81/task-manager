(function () {
  "use strict";

  /**
   * Shared Socket.IO client for chat and other realtime features.
   * Push-style toast popups for the "notification" event are disabled — use the
   * in-app notification panel (polls /notifications) instead.
   */
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

    socket.on("connect_error", function () {
      /* WebSocket-only: stay quiet; user still has the rest of the app. */
    });
  });
})();
