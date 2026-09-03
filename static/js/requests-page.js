(function () {
  function qs(sel, root) {
    return (root || document).querySelector(sel);
  }
  function qsa(sel, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(sel));
  }

  function wireCreateDialog() {
    var dialog = qs("#request-create-dialog");
    var openBtn = qs("#request-create-open");
    if (!dialog || !openBtn || typeof dialog.showModal !== "function") return;
    openBtn.addEventListener("click", function () {
      openBtn.setAttribute("aria-expanded", "true");
      dialog.showModal();
      var first = dialog.querySelector("input, select, textarea, button");
      if (first) first.focus();
    });
    qsa("[data-request-create-dialog-close]", dialog).forEach(function (btn) {
      btn.addEventListener("click", function () {
        dialog.close();
        openBtn.setAttribute("aria-expanded", "false");
        openBtn.focus();
      });
    });
    dialog.addEventListener("close", function () {
      openBtn.setAttribute("aria-expanded", "false");
    });
  }

  function wireStatusDialogs() {
    qsa("[data-request-dialog-open]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var id = btn.getAttribute("data-request-dialog-open");
        var dialog = id ? document.getElementById(id) : null;
        if (!dialog || typeof dialog.showModal !== "function") return;
        dialog.showModal();
        var first = dialog.querySelector("input, textarea, button[type='submit']");
        if (first) first.focus();
      });
    });
    qsa("[data-request-dialog-close]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var dialog = btn.closest("dialog");
        if (dialog) dialog.close();
      });
    });
  }

  function wireSubmitLock() {
    qsa("form").forEach(function (form) {
      if (!form.querySelector("[data-request-submit]")) return;
      form.addEventListener("submit", function () {
        qsa("[data-request-submit]", form).forEach(function (btn) {
          btn.disabled = true;
        });
      });
    });
  }

  function wireAssigneeFilter() {
    var project = qs("#request-form-project");
    var user = qs("#request-form-user");
    if (!project || !user) return;
    function sync() {
      var pid = project.value;
      qsa("option", user).forEach(function (opt) {
        if (!opt.value) {
          opt.hidden = false;
          opt.disabled = false;
          return;
        }
        var projects = (opt.getAttribute("data-projects") || "").split(",").filter(Boolean);
        var ok = !pid || projects.indexOf(pid) !== -1;
        opt.hidden = !ok;
        opt.disabled = !ok;
      });
      if (user.selectedOptions[0] && user.selectedOptions[0].disabled) {
        user.value = "";
      }
    }
    project.addEventListener("change", sync);
    sync();
  }

  wireCreateDialog();
  wireStatusDialogs();
  wireSubmitLock();
  wireAssigneeFilter();
})();
