/**
 * Shared "Complete material registration" modal.
 * Any element with [data-mr-reg-open][data-day-id] opens it. The server owns every
 * rule; this script renders the form, posts it once, and reloads (or opens the workflow).
 */
(function () {
  "use strict";

  var modal = document.querySelector("[data-mr-reg-modal]");
  if (!modal || typeof modal.showModal !== "function") return;
  var form = modal.querySelector("[data-mr-reg-form]");
  var browser = document.querySelector("[data-mr-reg-browse-modal]");
  var urlTemplate = modal.getAttribute("data-url-template") || "";
  var current = null;
  var busy = false;

  function $(sel, root) { return (root || modal).querySelector(sel); }
  function field(name) { return form.querySelector('[data-mr-reg-field="' + name + '"]'); }

  function csrfToken() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    return (meta && meta.content) || "";
  }

  function dayUrl(id) { return urlTemplate.replace(/\/0$/, "/" + encodeURIComponent(id)); }

  function getJson(url) {
    return fetch(url, { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (data) {
          if (!r.ok || data.ok === false) throw new Error(data.error || "Could not load registration (" + r.status + ").");
          return data;
        });
      });
  }

  function showError(msg) {
    var el = $("[data-mr-reg-error]");
    el.textContent = msg || "";
    el.hidden = !msg;
  }

  function setBusy(on) {
    busy = on;
    form.querySelectorAll("[data-mr-reg-submit]").forEach(function (b) { b.disabled = on || !current; });
  }

  function fillSelect(sel, items, value, groupKey) {
    var keepFirst = sel.querySelector("option");
    sel.innerHTML = "";
    if (keepFirst) sel.appendChild(keepFirst);
    var groups = {};
    items.forEach(function (it) {
      var opt = document.createElement("option");
      opt.value = String(it.value);
      opt.textContent = it.label;
      var parent = sel;
      if (groupKey && it[groupKey]) {
        if (!groups[it[groupKey]]) {
          groups[it[groupKey]] = document.createElement("optgroup");
          groups[it[groupKey]].label = it[groupKey];
          sel.appendChild(groups[it[groupKey]]);
        }
        parent = groups[it[groupKey]];
      }
      parent.appendChild(opt);
    });
    sel.value = value == null ? "" : String(value);
  }

  function syncMedia(key) {
    var checked = form.querySelector('[data-mr-reg-state="' + key + '"]:checked');
    var size = form.querySelector('[data-mr-reg-size="' + key + '"]');
    var present = checked && checked.value === "present";
    size.disabled = !present;
    if (!present) size.value = "";
  }

  function selectedVolume() {
    var id = field("source_volume_id").value;
    if (!current || !id || id === "other") return null;
    return current.options.volumes.find(function (v) { return String(v.id) === id; }) || null;
  }

  function syncSource() {
    var sel = field("source_volume_id");
    var other = sel.value === "other";
    field("source_label").hidden = !other;
    $("[data-mr-reg-browse]").disabled = !selectedVolume();
  }

  function render(data) {
    current = data;
    var d = data.day;
    var v = data.values;
    $("[data-mr-reg-sub]").textContent = d.project_name + " · " + d.label;
    var pill = $("[data-mr-reg-status]");
    pill.textContent = data.status.label;
    pill.className = "mr-reg-pill mr-reg-pill--" + data.status.key;
    var missing = $("[data-mr-reg-missing]");
    missing.hidden = !data.status.missing.length;
    missing.textContent = data.status.missing.length ? "Still missing: " + data.status.missing.join(", ") : "";

    field("project_id").value = d.project_id;
    field("shooting_day_id").value = d.id;
    form.querySelector('[data-mr-reg-text="project_name"]').textContent = d.project_name;
    form.querySelector('[data-mr-reg-text="day"]').textContent = "Unit " + d.unit_number + " · " + (d.day_name || "Day #" + d.id);
    var date = field("shooting_date");
    date.value = d.shooting_date || "";
    date.disabled = !data.can_edit_date;
    $("[data-mr-reg-date-hint]").hidden = !!data.can_edit_date;

    ["video", "audio"].forEach(function (key) {
      var state = v[key + "_state"] || "unknown";
      form.querySelectorAll('[data-mr-reg-state="' + key + '"]').forEach(function (r) { r.checked = r.value === state; });
      syncMedia(key);
      var size = v[key === "video" ? "video_size_tb" : "audio_size_gb"];
      if (state === "present" && size != null) form.querySelector('[data-mr-reg-size="' + key + '"]').value = size;
    });

    fillSelect(field("material_source"), data.options.material_sources.map(function (s) {
      return { value: s.key, label: s.label };
    }), v.material_source);

    var vols = data.options.volumes.map(function (o) {
      return {
        value: o.id,
        label: o.name + " · " + o.role_label + (o.mounted ? "" : " (not mounted)"),
        group: o.linked ? "Linked to this project" : "Other volumes",
      };
    });
    vols.push({ value: "other", label: "Other disk (not in Storage)…", group: "Other" });
    var sel = field("source_volume_id");
    fillSelect(sel, vols, v.source_volume_id || (v.source_label ? "other" : ""), "group");
    field("source_label").value = v.source_label || "";
    field("source_path").value = v.source_path || "";
    syncSource();

    fillSelect(field("responsible_user_id"), data.options.operators.map(function (o) {
      return { value: o.id, label: o.name };
    }), v.responsible_user_id || data.options.default_operator_id || "");
    field("notes").value = v.notes || "";

    var start = form.querySelector('[data-mr-reg-submit="start"]');
    start.textContent = data.workflow ? "Save and open workflow" : "Save and start workflow";
    $("[data-mr-reg-fields]").hidden = false;
    setBusy(false);
  }

  function open(dayId) {
    current = null;
    showError("");
    $("[data-mr-reg-fields]").hidden = true;
    $("[data-mr-reg-missing]").hidden = true;
    $("[data-mr-reg-sub]").textContent = "Loading…";
    $("[data-mr-reg-status]").textContent = "";
    setBusy(true);
    if (!modal.open) modal.showModal();
    getJson(dayUrl(dayId)).then(render).catch(function (err) {
      showError(err.message);
      $("[data-mr-reg-sub]").textContent = "";
    });
  }

  function payload(action) {
    var out = { action: action };
    ["shooting_date", "material_source", "source_path", "notes", "responsible_user_id"].forEach(function (k) {
      var el = field(k);
      if (!el.disabled) out[k] = el.value;
    });
    var vol = field("source_volume_id").value;
    out.source_volume_id = vol && vol !== "other" ? vol : "";
    out.source_label = vol === "other" ? field("source_label").value : "";
    ["video", "audio"].forEach(function (key) {
      var checked = form.querySelector('[data-mr-reg-state="' + key + '"]:checked');
      out[key + "_state"] = checked ? checked.value : "unknown";
      out[key === "video" ? "video_size_tb" : "audio_size_gb"] = form.querySelector('[data-mr-reg-size="' + key + '"]').value;
    });
    return out;
  }

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    if (busy || !current) return;
    var action = (e.submitter && e.submitter.value) || "save";
    showError("");
    setBusy(true);
    fetch(dayUrl(current.day.id), {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        "X-Requested-With": "XMLHttpRequest",
        "X-CSRFToken": csrfToken(),
      },
      body: JSON.stringify(payload(action)),
    })
      .then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (data) {
          if (!r.ok || !data.ok) throw new Error(data.error || "Could not save (" + r.status + ").");
          return data;
        });
      })
      .then(function (data) {
        if (data.redirect) window.location.href = data.redirect;
        else window.location.reload();
      })
      .catch(function (err) {
        showError(err.message);
        setBusy(false);
      });
  });

  form.querySelectorAll("[data-mr-reg-state]").forEach(function (r) {
    r.addEventListener("change", function () { syncMedia(r.getAttribute("data-mr-reg-state")); });
  });
  field("source_volume_id").addEventListener("change", syncSource);
  $("[data-mr-reg-close]").addEventListener("click", function () { modal.close(); });

  document.addEventListener("click", function (e) {
    var trigger = e.target.closest && e.target.closest("[data-mr-reg-open]");
    if (!trigger) return;
    e.preventDefault();
    var id = trigger.getAttribute("data-day-id");
    if (id) open(id);
  });

  // --- Folder browser (server-side listing; works the same in the desktop app) ---
  if (browser) {
    var bState = { url: "", rel: "", parent: "", abs: "" };
    var bList = $("[data-mr-reg-browse-list]", browser);
    var bCurrent = $("[data-mr-reg-browse-current]", browser);
    var bUp = $("[data-mr-reg-browse-up]", browser);
    var bSelect = $("[data-mr-reg-browse-select]", browser);
    var bErr = $("[data-mr-reg-browse-error]", browser);

    function load(rel) {
      bErr.hidden = true;
      $("[data-mr-reg-browse-loading]", browser).hidden = false;
      $("[data-mr-reg-browse-empty]", browser).hidden = true;
      bList.innerHTML = "";
      bSelect.disabled = true;
      getJson(bState.url + "?path=" + encodeURIComponent(rel || ""))
        .then(function (data) {
          bState.rel = data.relative_path || "";
          bState.parent = data.parent_path || "";
          bState.abs = data.absolute_path || "";
          bCurrent.textContent = bState.abs || "—";
          bUp.disabled = !bState.rel;
          bSelect.disabled = !bState.abs;
          (data.folders || []).forEach(function (f) {
            var li = document.createElement("li");
            var b = document.createElement("button");
            b.type = "button";
            b.className = "mr-reg-browse__folder";
            b.textContent = f.name;
            b.addEventListener("click", function () { load(f.path); });
            li.appendChild(b);
            bList.appendChild(li);
          });
          $("[data-mr-reg-browse-empty]", browser).hidden = (data.folders || []).length > 0;
        })
        .catch(function (err) {
          bCurrent.textContent = "—";
          bErr.textContent = err.message;
          bErr.hidden = false;
        })
        .then(function () { $("[data-mr-reg-browse-loading]", browser).hidden = true; });
    }

    $("[data-mr-reg-browse]").addEventListener("click", function () {
      var vol = selectedVolume();
      if (!vol) return;
      bState.url = vol.browse_url;
      browser.showModal();
      load("");
    });
    bUp.addEventListener("click", function () { load(bState.parent); });
    $("[data-mr-reg-browse-cancel]", browser).addEventListener("click", function () { browser.close(); });
    bSelect.addEventListener("click", function () {
      field("source_path").value = bState.abs;
      browser.close();
    });
  }
})();
