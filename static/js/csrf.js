/**
 * Global CSRF helpers for classic forms and fetch/XHR.
 * Expects <meta name="csrf-token" content="..."> from the server.
 */
(function () {
  "use strict";

  function getToken() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    return meta && meta.content ? meta.content : "";
  }

  function ensureFormToken(form) {
    if (!form || form.method.toLowerCase() === "get") return;
    var token = getToken();
    if (!token) return;
    var existing = form.querySelector('input[name="csrf_token"]');
    if (existing) {
      existing.value = token;
      return;
    }
    var input = document.createElement("input");
    input.type = "hidden";
    input.name = "csrf_token";
    input.value = token;
    form.appendChild(input);
  }

  function injectAllForms(root) {
    var forms = (root || document).querySelectorAll("form");
    for (var i = 0; i < forms.length; i++) {
      ensureFormToken(forms[i]);
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    injectAllForms(document);
    document.addEventListener(
      "submit",
      function (ev) {
        var form = ev.target;
        if (form && form.tagName === "FORM") ensureFormToken(form);
      },
      true
    );
  });

  // Patch fetch for same-origin mutating requests.
  if (typeof window.fetch === "function") {
    var originalFetch = window.fetch.bind(window);
    window.fetch = function (input, init) {
      init = init || {};
      var method = (init.method || "GET").toUpperCase();
      if (["POST", "PUT", "PATCH", "DELETE"].indexOf(method) !== -1) {
        var headers = new Headers(init.headers || {});
        if (!headers.has("X-CSRFToken") && !headers.has("X-CSRF-Token")) {
          var token = getToken();
          if (token) headers.set("X-CSRFToken", token);
        }
        init.headers = headers;
      }
      return originalFetch(input, init);
    };
  }

  // Patch XHR open/send for libraries that still use XMLHttpRequest.
  if (typeof XMLHttpRequest !== "undefined") {
    var xhrOpen = XMLHttpRequest.prototype.open;
    var xhrSend = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function (method) {
      this._tmCsrfMethod = (method || "GET").toUpperCase();
      return xhrOpen.apply(this, arguments);
    };
    XMLHttpRequest.prototype.send = function () {
      if (
        this._tmCsrfMethod &&
        ["POST", "PUT", "PATCH", "DELETE"].indexOf(this._tmCsrfMethod) !== -1
      ) {
        try {
          var token = getToken();
          if (token) this.setRequestHeader("X-CSRFToken", token);
        } catch (e) {
          /* header may already be set */
        }
      }
      return xhrSend.apply(this, arguments);
    };
  }

  window.TmCsrf = {
    getToken: getToken,
    ensureFormToken: ensureFormToken,
    injectAllForms: injectAllForms,
  };
})();
