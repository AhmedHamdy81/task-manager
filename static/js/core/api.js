/**
 * Fetch + JSON parsing (never throws raw HTML into JSON.parse).
 */
(function (global) {
  "use strict";

  global.TM = global.TM || {};

  function parseJsonBody(text, res) {
    var t = (text || "").trim();
    if (!t) {
      return {};
    }
    var c = t.charAt(0);
    if (c !== "{" && c !== "[" && c !== '"') {
      throw new Error(
        res && res.status
          ? "Server returned non-JSON (" + res.status + ")"
          : "Expected JSON response, got HTML or text"
      );
    }
    try {
      return JSON.parse(t);
    } catch (e) {
      throw new Error("Invalid JSON: " + (e.message || String(e)));
    }
  }

  global.TM.api = {
    fetchJson: function (url, options) {
      var opts = options || {};
      opts.credentials = opts.credentials || "same-origin";
      opts.headers = opts.headers || {};
      if (!opts.headers.Accept) {
        opts.headers.Accept = "application/json";
      }
      return fetch(url, opts).then(function (res) {
        return res.text().then(function (text) {
          if (!res.ok) {
            var raw = (text || "").trim();
            var msg = raw.slice(0, 240) || res.statusText || "Request failed (" + res.status + ")";
            if (raw.charAt(0) === "{") {
              try {
                var eb = JSON.parse(raw);
                if (eb && eb.detail) {
                  msg = String(eb.detail);
                } else if (eb && eb.error) {
                  msg = String(eb.error);
                } else if (eb && eb.message) {
                  msg = String(eb.message);
                }
              } catch (ignore) {
                /* keep msg from HTML/text body */
              }
            }
            throw new Error(msg);
          }
          return parseJsonBody(text, res);
        });
      });
    },

    getAdminTasks: function (params) {
      var q = new URLSearchParams();
      if (params.status) {
        q.set("status", params.status);
      }
      if (params.search) {
        q.set("search", params.search);
      }
      q.set("limit", String(params.limit != null ? params.limit : 20));
      q.set("offset", String(params.offset != null ? params.offset : 0));
      var base = params.apiUrl || "/api/tasks";
      var url = base + (base.indexOf("?") >= 0 ? "&" : "?") + q.toString();
      return global.TM.api.fetchJson(url);
    },
  };
})(typeof window !== "undefined" ? window : global);
