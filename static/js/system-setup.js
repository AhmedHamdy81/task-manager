(function () {
  "use strict";

  function isDesktopFolderPicker() {
    var desktop = window.taskManagerDesktop;
    return !!(desktop && typeof desktop.selectFolder === "function");
  }

  function csrfToken() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute("content") || "" : "";
  }

  function activateSection(section) {
    if (!section) return;
    var target = document.querySelector('[data-setup-section="' + section + '"]');
    if (target && typeof target.scrollIntoView === "function") {
      target.scrollIntoView({ behavior: "smooth", block: "start" });
    }
    document.querySelectorAll(".system-setup__nav-link").forEach(function (link) {
      link.classList.toggle("is-active", link.getAttribute("data-section") === section);
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    var params = new URLSearchParams(window.location.search || "");
    var section = (params.get("section") || "").trim().toLowerCase();
    if (section) activateSection(section);

    document.querySelectorAll(".system-setup__nav-link").forEach(function (link) {
      link.addEventListener("click", function () {
        var key = link.getAttribute("data-section") || "";
        if (key) activateSection(key);
      });
    });

    var seedForm = document.getElementById("system-setup-seed-form");
    if (seedForm) {
      var seedBtn = seedForm.querySelector("button[type=submit][data-confirm]");
      if (seedBtn) {
        var seedMessage = seedBtn.getAttribute("data-confirm") || "";
        seedForm.addEventListener("submit", function (ev) {
          if (!seedMessage) return;
          if (!window.confirm(seedMessage)) {
            ev.preventDefault();
          }
        });
      }
    }

    initEmailSection();
    initUploadSection();
    upgradeMailCheckSelectBtns();
  });

  function upgradeMailCheckSelectBtns() {
    document.querySelectorAll("#system-setup-email-form label.system-setup__check").forEach(function (label) {
      var input = label.querySelector('input[type="checkbox"]');
      var text = label.querySelector("span");
      if (!input || !text) return;
      label.className = "check check--select-btn system-setup__select-btn";
      if (!text.classList.contains("check-select-btn__text")) {
        text.classList.add("check-select-btn__text");
      }
      if (input.id) label.setAttribute("for", input.id);
    });
  }

  function initEmailSection() {
    var form = document.getElementById("system-setup-email-form");
    if (!form) return;

    var dirty = false;
    var saveState = document.getElementById("mail-save-state");
    var providerSelect = document.getElementById("mail-provider");
    var providerHelp = document.getElementById("mail-provider-help");
    var serverInput = document.getElementById("mail-server");
    var portInput = document.getElementById("mail-port");
    var encryptionSelect = document.getElementById("mail-encryption");
    var passwordInput = document.getElementById("mail-password");
    var replaceFlag = document.getElementById("mail-replace-password");
    var replaceBtn = document.getElementById("mail-password-replace");
    var toggleBtn = document.getElementById("mail-password-toggle");
    var testBtn = document.getElementById("mail-test-btn");
    var testRecipient = document.getElementById("mail-test-recipient");
    var testResult = document.getElementById("mail-test-result");
    var testing = false;
    var providers = {};
    try {
      providers = JSON.parse(form.getAttribute("data-providers") || "{}") || {};
    } catch (err) {
      providers = {};
    }

    function markDirty() {
      dirty = true;
      if (saveState) {
        saveState.textContent = form.getAttribute("data-unsaved-warn") || "Unsaved changes";
        saveState.classList.add("is-dirty");
      }
      updateTestEnabled();
      updatePreview();
    }

    function clearDirty() {
      dirty = false;
      if (saveState) {
        saveState.textContent = "";
        saveState.classList.remove("is-dirty");
      }
    }

    function applyProviderPreset(provider) {
      var meta = providers[provider] || providers.custom || {};
      if (serverInput && meta.server) serverInput.value = meta.server;
      if (portInput && meta.port) portInput.value = meta.port;
      if (encryptionSelect && meta.encryption) encryptionSelect.value = meta.encryption;
      if (providerHelp) {
        providerHelp.hidden = provider !== "gmail";
      }
    }

    function updateTestEnabled() {
      if (!testBtn) return;
      var server = (serverInput && serverInput.value) || "";
      var sender = (document.getElementById("mail-sender-email") || {}).value || "";
      var hasPw =
        (passwordInput && passwordInput.value && !passwordInput.readOnly) ||
        (passwordInput && passwordInput.placeholder);
      var ready = !!(server.trim() && sender.trim() && hasPw);
      testBtn.disabled = !ready || testing;
    }

    function updatePreview() {
      var expiryEl = document.getElementById("mail-preview-expiry");
      var publicEl = document.getElementById("mail-preview-public");
      var exampleEl = document.getElementById("mail-preview-example");
      var expiryInput = document.getElementById("mail-reset-expiry");
      var publicInput = document.getElementById("mail-public-url");
      var minutes = (expiryInput && expiryInput.value) || "60";
      var base = ((publicInput && publicInput.value) || "").replace(/\/+$/, "");
      if (expiryEl) expiryEl.textContent = minutes + " minutes";
      if (publicEl) publicEl.textContent = base || "—";
      if (exampleEl) {
        exampleEl.textContent =
          (base || "https://your-server.example.com") +
          "/reset-password/preview-token-not-real";
      }
    }

    form.querySelectorAll("input, select, textarea").forEach(function (el) {
      el.addEventListener("change", markDirty);
      el.addEventListener("input", markDirty);
    });

    window.addEventListener("beforeunload", function (ev) {
      if (!dirty) return;
      ev.preventDefault();
      ev.returnValue = "";
    });

    form.addEventListener("submit", function () {
      clearDirty();
    });

    if (providerSelect) {
      providerSelect.addEventListener("change", function () {
        applyProviderPreset(providerSelect.value);
        markDirty();
      });
    }

    if (replaceBtn && passwordInput && replaceFlag) {
      replaceBtn.addEventListener("click", function () {
        replaceFlag.value = "1";
        passwordInput.readOnly = false;
        passwordInput.value = "";
        passwordInput.placeholder = "";
        passwordInput.focus();
        if (toggleBtn) toggleBtn.hidden = false;
        replaceBtn.hidden = true;
        markDirty();
      });
    }

    if (toggleBtn && passwordInput) {
      toggleBtn.addEventListener("click", function () {
        if (passwordInput.readOnly) return;
        var show = passwordInput.type === "password";
        passwordInput.type = show ? "text" : "password";
        toggleBtn.textContent = show ? "Hide" : "Show";
      });
    }

    if (testBtn) {
      testBtn.addEventListener("click", function () {
        if (testing || testBtn.disabled) return;
        var recipient = (testRecipient && testRecipient.value) || "";
        if (!recipient.trim()) {
          if (testResult) {
            testResult.textContent = "Enter a recipient email address.";
            testResult.classList.add("is-error");
            testResult.classList.remove("is-ok");
          }
          return;
        }
        testing = true;
        testBtn.disabled = true;
        if (testResult) {
          testResult.textContent = "Sending…";
          testResult.classList.remove("is-error", "is-ok");
        }
        var body = new FormData(form);
        body.set("test_recipient", recipient.trim());
        fetch(testBtn.getAttribute("data-url") || "", {
          method: "POST",
          headers: {
            Accept: "application/json",
            "X-CSRFToken": csrfToken(),
          },
          body: body,
          credentials: "same-origin",
        })
          .then(function (res) {
            return res.json().then(function (data) {
              return { ok: res.ok, status: res.status, data: data || {} };
            });
          })
          .then(function (result) {
            if (testResult) {
              if (result.ok && result.data.ok) {
                testResult.textContent = result.data.message || "Test email sent.";
                testResult.classList.add("is-ok");
                testResult.classList.remove("is-error");
              } else {
                testResult.textContent =
                  (result.data && result.data.error) || "Test email failed.";
                testResult.classList.add("is-error");
                testResult.classList.remove("is-ok");
              }
            }
          })
          .catch(function () {
            if (testResult) {
              testResult.textContent = "Test email failed.";
              testResult.classList.add("is-error");
              testResult.classList.remove("is-ok");
            }
          })
          .finally(function () {
            testing = false;
            updateTestEnabled();
          });
      });
    }

    updateTestEnabled();
    updatePreview();
  }

  function initUploadSection() {
    var uploadRoot = document.getElementById("system-setup-upload");
    if (!uploadRoot) return;

    var input = document.getElementById("upload-directory-input");
    var chooseBtn = document.getElementById("upload-directory-choose");
    var chooseStatus = document.getElementById("upload-directory-choose-status");
    var form = document.getElementById("system-setup-upload-form");
    var useDialog = document.getElementById("upload-directory-use-dialog");
    var usePathEl = document.getElementById("upload-directory-use-path");
    var pendingUsePath = "";
    var choosing = false;

    function setChooseStatus(message, isError) {
      if (!chooseStatus) return;
      if (!message) {
        chooseStatus.hidden = true;
        chooseStatus.textContent = "";
        return;
      }
      chooseStatus.hidden = false;
      chooseStatus.textContent = message;
      chooseStatus.classList.toggle("is-error", !!isError);
    }

    function applyChosenPath(path) {
      if (!input || input.readOnly || !path) return;
      input.value = path;
      input.focus();
      setChooseStatus("");
    }

    function browseViaServer() {
      var url = (chooseBtn && chooseBtn.getAttribute("data-browse-url")) || "";
      if (!url) {
        setChooseStatus("Folder picker is unavailable in this browser. Paste an absolute path.", true);
        return Promise.resolve();
      }
      setChooseStatus("Opening Finder…");
      return fetch(url, {
        method: "POST",
        headers: {
          Accept: "application/json",
          "X-CSRFToken": csrfToken(),
        },
        credentials: "same-origin",
      })
        .then(function (res) {
          return res.json().then(function (data) {
            return { ok: res.ok, data: data || {} };
          });
        })
        .then(function (result) {
          if (result.data && result.data.canceled) {
            setChooseStatus("");
            return;
          }
          if (result.ok && result.data.ok && result.data.upload_directory) {
            applyChosenPath(result.data.upload_directory);
            return;
          }
          setChooseStatus(
            (result.data && result.data.error) ||
              "Could not open the folder picker. Paste an absolute path instead.",
            true
          );
        })
        .catch(function () {
          setChooseStatus("Could not open the folder picker. Paste an absolute path instead.", true);
        });
    }

    if (chooseBtn && input && !input.readOnly) {
      chooseBtn.hidden = false;
      chooseBtn.addEventListener("click", function () {
        if (choosing || chooseBtn.disabled) return;
        choosing = true;
        chooseBtn.disabled = true;

        var opener = null;
        if (isDesktopFolderPicker()) {
          opener = window.taskManagerDesktop.selectFolder().then(function (paths) {
            if (paths && paths[0]) {
              applyChosenPath(paths[0]);
              return;
            }
            setChooseStatus("");
          });
        } else {
          opener = browseViaServer();
        }

        Promise.resolve(opener)
          .catch(function () {
            setChooseStatus("Could not open the folder picker.", true);
          })
          .finally(function () {
            choosing = false;
            chooseBtn.disabled = false;
          });
      });
    }

    function closeUseDialog() {
      pendingUsePath = "";
      if (useDialog && useDialog.open) useDialog.close();
    }

    function submitUsePath(path) {
      if (!input || input.readOnly || !form || !path) return;
      input.value = path;
      if (typeof form.requestSubmit === "function") {
        form.requestSubmit();
      } else {
        form.submit();
      }
    }

    function openUseDialog(path) {
      pendingUsePath = path || "";
      if (!pendingUsePath) return;
      if (usePathEl) usePathEl.textContent = pendingUsePath;
      if (useDialog && typeof useDialog.showModal === "function") {
        useDialog.showModal();
        return;
      }
      if (window.confirm("Use this upload directory?\n\n" + pendingUsePath)) {
        submitUsePath(pendingUsePath);
      }
    }

    uploadRoot.querySelectorAll("[data-upload-history-use]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        if (!input || input.readOnly || !form) return;
        var path = btn.getAttribute("data-upload-history-use") || "";
        if (!path) return;
        openUseDialog(path);
      });
    });

    if (useDialog) {
      useDialog.querySelectorAll("[data-upload-use-cancel]").forEach(function (btn) {
        btn.addEventListener("click", function () {
          closeUseDialog();
        });
      });
      var confirmBtn = useDialog.querySelector("[data-upload-use-confirm]");
      if (confirmBtn) {
        confirmBtn.addEventListener("click", function () {
          var path = pendingUsePath;
          closeUseDialog();
          submitUsePath(path);
        });
      }
      useDialog.addEventListener("cancel", function () {
        pendingUsePath = "";
      });
    }

    uploadRoot.querySelectorAll("[data-safe-delete]").forEach(function (btn) {
      btn.addEventListener(
        "click",
        function (ev) {
          if (!window.SafeDelete || typeof window.SafeDelete.open !== "function") {
            return;
          }
          if (btn.disabled) return;
          ev.preventDefault();
          ev.stopImmediatePropagation();
          var path = btn.getAttribute("data-entity-name") || "";
          window.SafeDelete.open({
            entityType: btn.getAttribute("data-entity-type") || "",
            entityId: btn.getAttribute("data-entity-id") || "",
            entityName: path,
            entityLabel: btn.getAttribute("data-entity-label") || "Upload directory",
            deleteUrl: btn.getAttribute("data-delete-url") || "",
            warningText:
              btn.getAttribute("data-warning-text") ||
              "This removes the path from Directory history only. Files on disk are not deleted.",
            confirmButtonLabel: btn.getAttribute("data-confirm-label") || "Remove from history",
            modalTitle: btn.getAttribute("data-modal-title") || "Safe Delete",
            modalDesc:
              btn.getAttribute("data-modal-desc") ||
              "You are about to remove this directory from history:",
            successRedirect: btn.getAttribute("data-success-redirect") || "",
            extraBody: { upload_directory: path },
          });
        },
        true
      );
    });
  }
})();
