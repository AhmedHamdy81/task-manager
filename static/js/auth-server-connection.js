(function () {
  "use strict";

  function parsed(value) {
    try {
      return new URL(String(value || "").trim());
    } catch (err) {
      return null;
    }
  }

  function normalizeServerUrl(value) {
    var url = parsed(value);
    if (!url || url.username || url.password || url.search || url.hash || !url.hostname) {
      return null;
    }
    if (url.protocol !== "https:" && url.protocol !== "http:") {
      return null;
    }
    url.pathname = url.pathname.replace(/\/+$/, "") || "/";
    return url.toString();
  }

  function hasDesktopBridge() {
    return !!(window.bigbangSetup && typeof window.bigbangSetup.saveServer === "function");
  }

  async function currentAddress() {
    if (hasDesktopBridge() && typeof window.bigbangSetup.getServer === "function") {
      try {
        var stored = await window.bigbangSetup.getServer();
        if (stored) {
          return stored;
        }
      } catch (err) {
        /* fall through to the page origin */
      }
    }
    return window.location.origin;
  }

  function loginUrlFor(normalized) {
    var dest = new URL(normalized);
    dest.pathname = "/login";
    dest.search = "";
    dest.hash = "";
    return dest.toString();
  }

  function elements() {
    return {
      dialog: document.getElementById("auth-server-dialog"),
      form: document.getElementById("auth-server-form"),
      input: document.getElementById("auth-server-url"),
      err: document.getElementById("auth-server-error"),
    };
  }

  function setError(message) {
    var err = elements().err;
    if (!err) {
      return;
    }
    err.textContent = message || "";
    err.hidden = !message;
  }

  function invalidMessage() {
    var err = elements().err;
    return (err && err.getAttribute("data-invalid")) || "Enter an http:// or https:// server address.";
  }

  function closeDialog() {
    var dialog = elements().dialog;
    if (!dialog) {
      return;
    }
    if (typeof dialog.close === "function") {
      dialog.close();
    } else {
      dialog.removeAttribute("open");
    }
  }

  function openDialog() {
    var els = elements();
    if (!els.dialog || !els.input) {
      return;
    }
    setError("");
    currentAddress().then(function (address) {
      els.input.value = address;
      if (typeof els.dialog.showModal === "function") {
        if (!els.dialog.open) {
          els.dialog.showModal();
        }
      } else {
        els.dialog.setAttribute("open", "");
      }
      els.input.focus();
      els.input.select();
    });
  }

  function saveConnection() {
    var input = elements().input;
    if (!input) {
      return;
    }
    setError("");
    var next = normalizeServerUrl(input.value);
    if (!next) {
      setError(invalidMessage());
      return;
    }
    currentAddress().then(function (current) {
      var currentUrl = parsed(current);
      var nextUrl = parsed(next);
      var sameOrigin = !!(currentUrl && nextUrl && currentUrl.origin === nextUrl.origin);
      if (hasDesktopBridge()) {
        return window.bigbangSetup.saveServer(next).then(function (result) {
          if (!result || !result.ok) {
            setError((result && result.error) || invalidMessage());
          }
        });
      }
      if (sameOrigin) {
        closeDialog();
        return;
      }
      window.location.assign(loginUrlFor(next));
    });
  }

  window.authServerOpen = openDialog;
  window.authServerClose = closeDialog;

  document.addEventListener("click", function (event) {
    var target = event.target;
    if (!target || typeof target.closest !== "function") {
      return;
    }
    if (target.closest("#auth-server-open")) {
      event.preventDefault();
      openDialog();
      return;
    }
    if (target.closest("#auth-server-cancel")) {
      event.preventDefault();
      closeDialog();
      return;
    }
    if (target.closest("#auth-server-save")) {
      event.preventDefault();
      saveConnection();
      return;
    }
    var dialog = elements().dialog;
    if (dialog && event.target === dialog) {
      closeDialog();
    }
  });

  document.addEventListener("submit", function (event) {
    if (event.target.id !== "auth-server-form") {
      return;
    }
    event.preventDefault();
    saveConnection();
  });
})();
