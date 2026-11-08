(function () {
  "use strict";

  function $all(root, sel) {
    return Array.prototype.slice.call(root.querySelectorAll(sel));
  }

  // --- Worksheets step -------------------------------------------------------
  function initSheets(form) {
    function syncLayout() {
      var checked = form.querySelector('input[name="layout"]:checked');
      form.setAttribute("data-layout", checked ? checked.value : "table");
    }
    $all(form, 'input[name="layout"]').forEach(function (r) {
      r.addEventListener("change", syncLayout);
    });
    syncLayout();
    $all(form, "[data-pim-sheet]").forEach(function (card) {
      var input = card.querySelector("[data-pim-header-input]");
      var body = card.querySelector("[data-pim-sheet-rows]");
      function mark() {
        var n = parseInt(input.value, 10) || 1;
        $all(card, "tr[data-row-number]").forEach(function (tr) {
          var rn = parseInt(tr.getAttribute("data-row-number"), 10);
          tr.classList.toggle("is-header", rn === n);
          tr.classList.toggle("is-skipped", rn < n);
        });
      }
      input.addEventListener("input", mark);
      body.addEventListener("click", function (ev) {
        var tr = ev.target.closest("tr[data-row-number]");
        if (!tr) return;
        input.value = tr.getAttribute("data-row-number");
        mark();
      });
      var more = card.querySelector("[data-pim-sheet-more]");
      if (more) more.addEventListener("click", function () { loadRows(card, more, mark); });
      mark();
    });
    initSheetPicker(form);
  }

  function loadRows(card, btn, mark) {
    var body = card.querySelector("[data-pim-sheet-rows]");
    var count = card.querySelector("[data-pim-sheet-count]");
    btn.disabled = true;
    btn.textContent = "Loading…";
    fetch(btn.getAttribute("data-url"), { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
      .then(function (data) {
        var frag = document.createDocumentFragment();
        data.rows.forEach(function (row, k) {
          var n = data.start + k + 1;
          var tr = document.createElement("tr");
          tr.setAttribute("data-row-number", String(n));
          var th = document.createElement("th");
          th.scope = "row";
          th.className = "pim-rownum";
          th.textContent = String(n);
          tr.appendChild(th);
          row.forEach(function (cell) {
            var td = document.createElement("td");
            td.className = "pim-cell pim-cell--" + cell[0];
            td.title = cell[1];
            td.textContent = cell[1].length > 40 ? cell[1].slice(0, 39) + "…" : cell[1];
            tr.appendChild(td);
          });
          frag.appendChild(tr);
        });
        body.appendChild(frag);
        count.textContent = "Showing all " + data.total + " rows";
        btn.remove();
        mark();
      })
      .catch(function () {
        btn.disabled = false;
        btn.textContent = "Could not load rows — try again";
      });
  }

  function initSheetPicker(form) {
    var bar = form.querySelector("[data-pim-sheetpicker]");
    var modal = form.querySelector("[data-pim-sheet-modal]");
    if (!bar || !modal) return;
    var boxes = $all(modal, "[data-pim-sheet-toggle]");
    var names = bar.querySelector("[data-pim-sheets-summary]");
    var count = modal.querySelector("[data-pim-sheets-count]");
    var apply = modal.querySelector("[data-pim-sheets-apply]");
    var saved = [];

    function nameOf(box) { return box.value; }
    function chosen() { return boxes.filter(function (b) { return b.checked; }); }

    function syncModal() {
      var n = chosen().length;
      count.textContent = n === 0 ? "Select at least one worksheet." : n + " of " + boxes.length + " selected.";
      count.classList.toggle("pim-err", n === 0);
      apply.disabled = n === 0;
    }

    function syncPage() {
      boxes.forEach(function (box) {
        var card = form.querySelector('[data-pim-sheet="' + box.getAttribute("data-pim-sheet-toggle") + '"]');
        if (card) card.classList.toggle("is-off", !box.checked);
      });
      var list = chosen().map(nameOf);
      names.textContent = list.length ? list.join(" · ") : "No worksheet selected";
      names.classList.toggle("pim-err", !list.length);
    }

    function open() {
      saved = boxes.map(function (b) { return b.checked; });
      syncModal();
      if (typeof modal.showModal === "function") modal.showModal();
      else modal.setAttribute("open", "");
    }

    function close() {
      if (typeof modal.close === "function") modal.close();
      else modal.removeAttribute("open");
    }

    boxes.forEach(function (box) { box.addEventListener("change", syncModal); });
    modal.querySelector("[data-pim-sheets-all]").addEventListener("click", function () {
      boxes.forEach(function (b) { b.checked = true; });
      syncModal();
    });
    modal.querySelector("[data-pim-sheets-none]").addEventListener("click", function () {
      boxes.forEach(function (b) { b.checked = false; });
      syncModal();
    });
    apply.addEventListener("click", function () {
      if (!chosen().length) return;
      close();
      syncPage();
    });
    function cancel() {
      boxes.forEach(function (b, i) { b.checked = saved[i]; });
      syncPage();
    }
    modal.querySelector("[data-pim-sheets-cancel]").addEventListener("click", function () {
      cancel();
      close();
    });
    modal.addEventListener("cancel", cancel);
    var openBtn = bar.querySelector("[data-pim-sheets-open]");
    if (openBtn) openBtn.addEventListener("click", open);

    form.addEventListener("submit", function (ev) {
      if (ev.submitter && ev.submitter.getAttribute("form") === "pim-cancel-form") return;
      if (!chosen().length) {
        ev.preventDefault();
        open();
      }
    });
    syncPage();
    if (bar.getAttribute("data-autopen") === "1") open();
  }

  // --- Preview step ----------------------------------------------------------
  function rowTarget(tr) {
    var match = tr.getAttribute("data-match");
    if (match) return match;
    var cand = tr.querySelector("[data-pim-cand]:checked");
    return cand ? cand.value : "";
  }

  function syncRow(tr) {
    var sel = tr.querySelector("[data-pim-action]");
    var action = sel ? sel.value : "skip";
    var target = rowTarget(tr);
    $all(tr, "[data-pim-target]").forEach(function (block) {
      block.hidden = block.getAttribute("data-pim-target") !== target;
    });
    tr.setAttribute("data-action", action);
  }

  function collect(form) {
    var out = {};
    var problems = [];
    $all(form, "tr[data-pim-row]").forEach(function (tr) {
      var id = tr.getAttribute("data-pim-row");
      var sel = tr.querySelector("[data-pim-action]");
      var action = sel ? sel.value : "skip";
      var entry = { action: action };
      if (action === "update") {
        var target = rowTarget(tr);
        var block = target ? tr.querySelector('[data-pim-target="' + target + '"]') : null;
        entry.target_id = target ? parseInt(target, 10) : null;
        entry.fields = block ? $all(block, "[data-pim-field]:checked").map(function (i) { return i.getAttribute("data-pim-field"); }) : [];
        entry.clear = block ? $all(block, "[data-pim-clear]:checked").map(function (i) { return i.getAttribute("data-pim-clear"); }) : [];
        var where = id.replace(/!(\d+)$/, " row $1");
        if (!target) problems.push(where + ": choose the existing row to update.");
        else if (!entry.fields.length && !entry.clear.length) problems.push(where + ": select at least one field, or keep the row.");
      }
      out[id] = entry;
    });
    return { decisions: out, problems: problems };
  }

  function initPreview(form) {
    var rows = $all(form, "tr[data-pim-row]");
    rows.forEach(function (tr) {
      var sel = tr.querySelector("[data-pim-action]");
      if (sel) sel.addEventListener("change", function () { syncRow(tr); });
      $all(tr, "[data-pim-cand]").forEach(function (r) {
        r.addEventListener("change", function () {
          if (sel && sel.value === "skip" && Array.prototype.some.call(sel.options, function (o) { return o.value === "update"; })) {
            sel.value = "update";
          }
          syncRow(tr);
        });
      });
      $all(tr, "[data-pim-field], [data-pim-clear]").forEach(function (box) {
        box.addEventListener("change", function () {
          if (box.checked && sel && Array.prototype.some.call(sel.options, function (o) { return o.value === "update"; })) {
            sel.value = "update";
            syncRow(tr);
          }
        });
      });
      syncRow(tr);
    });

    $all(document, "[data-pim-filter]").forEach(function (chip) {
      chip.addEventListener("click", function () {
        var f = chip.getAttribute("data-pim-filter");
        $all(document, "[data-pim-filter]").forEach(function (c) { c.classList.toggle("is-active", c === chip); });
        rows.forEach(function (tr) {
          tr.hidden = f !== "all" && tr.getAttribute("data-status") !== f;
        });
      });
    });

    $all(form, "[data-pim-bulk]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var kind = btn.getAttribute("data-pim-bulk");
        rows.forEach(function (tr) {
          var status = tr.getAttribute("data-status");
          var sel = tr.querySelector("[data-pim-action]");
          if (!sel || sel.disabled) return;
          if (kind === "add-new" && status === "new") sel.value = "add";
          if (kind === "skip-new" && status === "new") sel.value = "skip";
          if (kind === "keep-changed" && status === "changed") sel.value = "skip";
          if (kind === "update-changed" && status === "changed") {
            var block = tr.querySelector('[data-pim-target="' + tr.getAttribute("data-match") + '"]');
            var safe = block ? $all(block, "[data-pim-field]:not([data-identity])") : [];
            if (!safe.length) return;
            sel.value = "update";
            syncRow(tr);
            safe.forEach(function (i) { i.checked = true; });
          }
          syncRow(tr);
        });
      });
    });

    var errorBox = form.querySelector("[data-pim-client-error]");
    form.addEventListener("submit", function (ev) {
      var res = collect(form);
      if (res.problems.length) {
        ev.preventDefault();
        if (errorBox) {
          errorBox.textContent = res.problems.slice(0, 5).join(" ") + (res.problems.length > 5 ? " …" : "");
          errorBox.hidden = false;
          errorBox.scrollIntoView({ block: "center" });
        }
        return;
      }
      form.querySelector("[data-pim-decisions]").value = JSON.stringify(res.decisions);
    });
  }

  function initDays() {
    $all(document, "[data-pim-day-choice]").forEach(function (sel) {
      var cell = sel.closest(".pim-day__use");
      var create = cell ? cell.querySelector("[data-pim-day-create]") : null;
      if (!create) return;
      var date = create.querySelector("[data-pim-day-date]");
      function sync() {
        create.hidden = sel.value !== "create";
        if (date) date.required = !create.hidden;
      }
      sel.addEventListener("change", sync);
      sync();
    });
    $all(document, "[data-pim-dayall]").forEach(function (form) {
      var choice = form.querySelector("[data-pim-dayall-choice]");
      var start = form.querySelector('input[name="all_start"]');
      function sync() {
        var creating = choice.value === "create";
        $all(form, "[data-pim-dayall-create]").forEach(function (el) { el.hidden = !creating; });
        if (start) start.required = creating;
      }
      choice.addEventListener("change", sync);
      sync();
    });
  }

  function initConfirm(form) {
    form.addEventListener("submit", function () {
      var btn = form.querySelector('button[type="submit"].btn--primary');
      if (btn) {
        btn.disabled = true;
        btn.textContent = "Importing…";
      }
    });
  }

  function initDrop(drop) {
    var input = drop.querySelector("[data-pim-file]");
    var nameEl = drop.querySelector("[data-pim-file-name]");
    var errEl = drop.querySelector("[data-pim-file-error]");
    var original = nameEl.innerHTML;
    var form = drop.closest("form");

    function check() {
      var file = input.files && input.files[0];
      drop.classList.remove("has-file", "has-error");
      errEl.hidden = true;
      if (!file) {
        nameEl.innerHTML = original;
        return true;
      }
      nameEl.textContent = file.name;
      if (!/\.(xlsx|csv)$/i.test(file.name)) {
        drop.classList.add("has-error");
        errEl.textContent = "Only .xlsx and .csv files can be imported.";
        errEl.hidden = false;
        return false;
      }
      drop.classList.add("has-file");
      return true;
    }

    input.addEventListener("change", check);
    ["dragenter", "dragover"].forEach(function (t) {
      drop.addEventListener(t, function (ev) {
        ev.preventDefault();
        drop.classList.add("is-dragover");
      });
    });
    ["dragleave", "drop"].forEach(function (t) {
      drop.addEventListener(t, function () { drop.classList.remove("is-dragover"); });
    });
    drop.addEventListener("drop", function (ev) {
      ev.preventDefault();
      var files = ev.dataTransfer && ev.dataTransfer.files;
      if (!files || !files.length) return;
      var dt = new DataTransfer();
      dt.items.add(files[0]);
      input.files = dt.files;
      check();
    });
    if (form) {
      form.addEventListener("submit", function (ev) {
        if (!(input.files && input.files.length)) {
          ev.preventDefault();
          drop.classList.add("has-error");
          errEl.textContent = "Choose an .xlsx or .csv file first.";
          errEl.hidden = false;
          return;
        }
        if (!check()) ev.preventDefault();
      });
    }
  }

  function initBusy() {
    $all(document, "[data-pim-busy]").forEach(function (btn) {
      var form = btn.form || btn.closest("form");
      if (!form) return;
      form.addEventListener("submit", function () {
        setTimeout(function () {
          btn.disabled = true;
          btn.textContent = btn.getAttribute("data-pim-busy");
        }, 0);
      });
    });
  }

  function initHandoff(box) {
    var statusUrl = box.getAttribute("data-status-url");
    var returnUrl = box.getAttribute("data-return-url");
    var stateEl = box.querySelector("[data-pim-handoff-state]");
    var started = Date.now();
    var messages = {
      started: "Finish connecting in your browser…",
      cancelled: "The connection was cancelled in the browser. Close this page or start again.",
      connected: "Connected. Continuing…"
    };
    function poll() {
      if (Date.now() - started > 10 * 60 * 1000) {
        stateEl.textContent = "This connection attempt expired. Start again.";
        return;
      }
      fetch(statusUrl, { credentials: "same-origin", headers: { Accept: "application/json" } })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (data) {
          var result = data && data.result;
          if (result === "connected") {
            stateEl.textContent = messages.connected;
            window.location.href = returnUrl;
            return;
          }
          if (result && result !== "waiting" && result !== "started") {
            stateEl.textContent = messages[result] || "The connection did not complete. Start again.";
            return;
          }
          if (result === "started") stateEl.textContent = messages.started;
          setTimeout(poll, 2500);
        })
        .catch(function () { setTimeout(poll, 5000); });
    }
    poll();
  }

  document.addEventListener("DOMContentLoaded", function () {
    var drop = document.querySelector("[data-pim-drop]");
    if (drop) initDrop(drop);
    initBusy();
    $all(document, "[data-pim-map-select]").forEach(function (sel) {
      sel.addEventListener("change", function () {
        var tr = sel.closest("tr");
        if (tr) tr.classList.toggle("is-ignored", !sel.value);
      });
    });
    var handoff = document.querySelector("[data-pim-handoff]");
    if (handoff) initHandoff(handoff);
    var sheets = document.querySelector("[data-pim-sheets]");
    if (sheets) initSheets(sheets);
    var rowsForm = document.querySelector("[data-pim-rows]");
    if (rowsForm) initPreview(rowsForm);
    initDays();
    var confirm = document.querySelector("[data-pim-confirm]");
    if (confirm) initConfirm(confirm);
  });
})();
