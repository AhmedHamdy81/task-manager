/**
 * Machine Room guided media workflow — Mission Control UI.
 * Server is the authority; this script only posts actions and reloads on success.
 */
(function () {
  "use strict";

  function csrfToken() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    if (meta && meta.content) return meta.content;
    var root = document.querySelector("[data-mr-wf-root]");
    return (root && root.getAttribute("data-csrf-token")) || "";
  }

  function postJson(url, body) {
    return fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        "X-Requested-With": "XMLHttpRequest",
        "X-CSRFToken": csrfToken(),
      },
      body: JSON.stringify(body || {}),
      credentials: "same-origin",
    }).then(function (r) {
      return r.json().then(function (data) {
        return { ok: r.ok && data && data.ok !== false, status: r.status, data: data };
      });
    });
  }

  function reloadWithWorkflow(id) {
    var u = new URL(window.location.href);
    u.searchParams.set("workflow_id", String(id));
    window.location.href = u.toString();
  }

  function reloadPage() {
    window.location.reload();
  }

  function showError(msg) {
    window.alert(msg || "Something went wrong. Try again.");
  }

  function collectedChecks(selector) {
    return Array.prototype.map
      .call(document.querySelectorAll(selector + ":checked"), function (el) {
        return el.value;
      })
      .filter(Boolean);
  }

  function initStartForm(root) {
    var form = root.querySelector("[data-mr-wf-start-form]");
    if (!form) return;
    var projectSel = form.querySelector("[data-mr-wf-project]");
    var daysModal = root.querySelector("[data-mr-wf-start-days-modal]");
    var daysOpen = form.querySelector("[data-mr-wf-days-open]");
    var daysSummary = form.querySelector("[data-mr-wf-days-summary]");
    var pick = daysModal.querySelector("[data-mr-wf-day-pick]");
    var committed = [];
    var emptyMsg = pick.querySelector("[data-mr-wf-day-empty]");
    var addBtn = pick.querySelector("[data-mr-wf-day-add]");
    var sep = pick.querySelector("[data-mr-wf-day-sep]");
    var list = pick.querySelector("[data-mr-wf-day-list]");
    var countEl = form.querySelector("[data-mr-wf-day-count]");
    var startError = root.querySelector("[data-mr-wf-start-error]");
    var daysJson = document.getElementById("mr-wf-days-json");
    var daysByProject = {};
    try {
      daysByProject = JSON.parse(daysJson ? daysJson.textContent : "{}") || {};
    } catch (e) {
      daysByProject = {};
    }

    var newDay = root.querySelector("[data-mr-wf-new-day]");
    var shuttleSel = form.querySelector("[data-mr-wf-start-shuttle]");
    var shuttleHint = form.querySelector("[data-mr-wf-start-shuttle-hint]");
    var shuttleJson = document.getElementById("mr-wf-shuttle-json");
    var shuttleByProject = {};
    try {
      shuttleByProject = JSON.parse(shuttleJson ? shuttleJson.textContent : "{}") || {};
    } catch (e) {
      shuttleByProject = {};
    }

    var SHUTTLE_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><rect x="7" y="8" width="10" height="10" rx="1"/><path d="M3 12h4M17 12h4M5 10l-2 2 2 2M19 10l2 2-2 2"/></svg>';

    function shuttleCard(v) {
      var label = document.createElement("label");
      label.className = "mr-mc__vol-card mr-mc__vol-card--transfer" + (v.mounted ? "" : " mr-mc__vol-card--offline");
      var input = document.createElement("input");
      input.type = "radio";
      input.name = "mr-wf-start-shuttle";
      input.value = v.id;
      label.appendChild(input);
      label.insertAdjacentHTML(
        "beforeend",
        '<span class="mr-mc__vol-card-check" aria-hidden="true">✓</span>' +
        '<span class="mr-mc__vol-card-icon" aria-hidden="true">' + SHUTTLE_ICON + "</span>" +
        '<span class="mr-mc__vol-card-name"></span>' +
        '<span class="mr-mc__vol-card-role">Linked to project</span>' +
        '<span class="mr-mc__vol-card-status"><span class="mr-mc__vol-card-mount"></span>' +
        '<span class="mr-mc__vol-card-free"></span></span>'
      );
      label.querySelector(".mr-mc__vol-card-name").textContent = v.name;
      label.querySelector(".mr-mc__vol-card-mount").textContent = v.mounted ? "Mounted" : "Not mounted";
      label.querySelector(".mr-mc__vol-card-free").textContent =
        v.free_pct === null || v.free_pct === undefined ? "Needs scan" : v.free_pct + "% free";
      label.addEventListener("pointerdown", function () {
        input.dataset.wasChecked = input.checked ? "1" : "";
      });
      input.addEventListener("click", function () {
        if (input.dataset.wasChecked !== "1") return;
        input.dataset.wasChecked = "";
        input.checked = false;
        syncShuttleHint();
      });
      input.addEventListener("change", syncShuttleHint);
      return label;
    }

    function selectedShuttle() {
      var el = shuttleSel ? shuttleSel.querySelector("input[name='mr-wf-start-shuttle']:checked") : null;
      return el ? parseInt(el.value, 10) : null;
    }

    function syncShuttleHint() {
      if (!shuttleHint) return;
      var pid = projectSel.value;
      var vols = pid ? (shuttleByProject[pid] || shuttleByProject[String(pid)] || []) : [];
      if (pid && !vols.length) {
        shuttleHint.textContent = "No Transfer / Shuttle drive is linked to this project. Link it on Storage, or pick it at the Receive step.";
      } else if (pid && !selectedShuttle()) {
        shuttleHint.textContent = "No drive picked — the workflow opens at the Receive step.";
      } else {
        shuttleHint.textContent = "Picking the shuttle drive records the material as received, so the workflow opens at Backup.";
      }
    }

    var drivesField = shuttleSel ? shuttleSel.closest("[data-mr-wf-drives-url]") : null;
    var FINDER_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="11" cy="11" r="6"/><path d="M20 20l-4.2-4.2M11 8v6M8 11h6"/></svg>';
    var foundByProject = {};
    var finderState = { busy: false, note: "" };

    function foundCard(drive) {
      var card = document.createElement("div");
      card.className = "mr-mc__vol-card mr-mc__vol-card--transfer mr-mc__vol-card--found";
      card.insertAdjacentHTML(
        "beforeend",
        '<span class="mr-mc__vol-card-badge"></span>' +
        '<span class="mr-mc__vol-card-icon" aria-hidden="true">' + SHUTTLE_ICON + "</span>" +
        '<span class="mr-mc__vol-card-name"></span>' +
        '<span class="mr-mc__vol-card-role"></span>' +
        '<button type="button" class="btn btn-secondary btn-sm mr-mc__vol-card-action"></button>'
      );
      card.querySelector(".mr-mc__vol-card-badge").textContent = drive.volume_id ? "Not linked" : "New drive";
      card.querySelector(".mr-mc__vol-card-name").textContent = drive.name;
      card.querySelector(".mr-mc__vol-card-role").textContent = [
        drive.capacity_tb ? drive.capacity_tb + " TB" : "",
        drive.capacity_tb ? drive.free_pct + "% free" : "",
      ].filter(Boolean).join(" · ") || drive.mount_path;
      card.title = drive.mount_path;
      var btn = card.querySelector(".mr-mc__vol-card-action");
      btn.textContent = drive.volume_id ? "Link to project" : "Add as shuttle";
      btn.addEventListener("click", function () {
        var pid = projectSel.value;
        btn.disabled = true;
        var payload = drive.volume_id ? { volume_id: drive.volume_id } : { mount_path: drive.mount_path };
        postJson(drivesField.getAttribute("data-mr-wf-drives-add-url"), Object.assign({ project_id: parseInt(pid, 10) }, payload))
          .then(function (res) {
            if (!res.ok) {
              btn.disabled = false;
              finderState.note = (res.data && res.data.error) || "Could not add the drive.";
              renderShuttles(selectedShuttle());
              return;
            }
            var list = shuttleByProject[pid] || shuttleByProject[String(pid)] || [];
            if (!list.some(function (v) { return v.id === res.data.volume.id; })) list.push(res.data.volume);
            shuttleByProject[String(pid)] = list;
            foundByProject[String(pid)] = (foundByProject[String(pid)] || []).filter(function (d) { return d !== drive; });
            finderState.note = "";
            renderShuttles(res.data.volume.id);
          })
          .catch(function () {
            btn.disabled = false;
            finderState.note = "Could not add the drive. Please try again.";
            renderShuttles(selectedShuttle());
          });
      });
      return card;
    }

    function finderCard() {
      var tile = document.createElement("button");
      tile.type = "button";
      tile.className = "mr-mc__vol-card mr-mc__vol-card--finder" + (finderState.busy ? " is-busy" : "");
      tile.disabled = finderState.busy;
      tile.insertAdjacentHTML(
        "beforeend",
        '<span class="mr-mc__vol-card-icon" aria-hidden="true">' + FINDER_ICON + "</span>" +
        '<span class="mr-mc__vol-card-name"></span>' +
        '<span class="mr-mc__vol-card-role"></span>'
      );
      tile.querySelector(".mr-mc__vol-card-name").textContent = finderState.busy ? "Looking…" : "Find connected drives";
      tile.querySelector(".mr-mc__vol-card-role").textContent = finderState.note || "Drives plugged in but not in the system";
      tile.addEventListener("click", findDrives);
      return tile;
    }

    function findDrives() {
      var pid = projectSel.value;
      if (!pid || !drivesField || finderState.busy) return;
      var keep = selectedShuttle();
      finderState.busy = true;
      finderState.note = "";
      renderShuttles(keep);
      var url = drivesField.getAttribute("data-mr-wf-drives-url") + "?project_id=" + encodeURIComponent(pid);
      fetch(url, { headers: { Accept: "application/json" }, credentials: "same-origin" })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (!data || data.ok === false) {
            finderState.note = (data && data.error) || "Could not look for drives.";
            return;
          }
          var found = (data.new || []).concat(data.linkable || []);
          foundByProject[String(pid)] = found;
          finderState.note = found.length ? "" : "No new drives — all connected drives are in the system";
        })
        .catch(function () { finderState.note = "Could not look for drives. Try again."; })
        .finally(function () {
          finderState.busy = false;
          renderShuttles(keep);
        });
    }

    function renderShuttles(selectId) {
      if (!shuttleSel) return;
      var pid = projectSel.value;
      var vols = pid ? (shuttleByProject[pid] || shuttleByProject[String(pid)] || []) : [];
      shuttleSel.innerHTML = "";
      if (!pid) {
        var empty = document.createElement("p");
        empty.className = "muted mr-mc__start-vols-empty";
        empty.textContent = "Select project first…";
        shuttleSel.appendChild(empty);
        syncShuttleHint();
        return;
      }
      vols.forEach(function (v) { shuttleSel.appendChild(shuttleCard(v)); });
      (foundByProject[String(pid)] || []).forEach(function (d) { shuttleSel.appendChild(foundCard(d)); });
      if (drivesField) shuttleSel.appendChild(finderCard());
      var pickId = selectId;
      if (pickId === undefined) {
        var mounted = vols.filter(function (v) { return v.mounted; });
        var pick = vols.length === 1 ? vols[0] : (mounted.length === 1 ? mounted[0] : null);
        pickId = pick ? pick.id : null;
      }
      if (pickId) {
        var input = shuttleSel.querySelector("input[value='" + pickId + "']");
        if (input) input.checked = true;
      }
      syncShuttleHint();
    }

    function setStartError(msg) {
      if (!startError) return;
      startError.textContent = msg || "";
      startError.hidden = !msg;
    }

    var triedStart = false;

    function markMissing(tried) {
      if (tried !== undefined) triedStart = tried;
      var projField = projectSel.closest(".mr-mc__field");
      var dayField = daysOpen.closest(".mr-mc__field");
      var missingProject = !projectSel.value;
      var missingDay = !committed.length;
      projField.classList.toggle("is-missing", triedStart && missingProject);
      dayField.classList.toggle("is-missing", triedStart && missingDay);
      return missingProject ? projectSel : (missingDay ? daysOpen : null);
    }

    function checkedDayIds() {
      return Array.prototype.map.call(
        list.querySelectorAll("[data-mr-wf-day]:checked"),
        function (el) { return parseInt(el.value, 10); }
      );
    }

    function projectDays() {
      return daysByProject[projectSel.value] || daysByProject[String(projectSel.value)] || [];
    }

    function updateCount() {
      var n = committed.length;
      if (countEl) countEl.textContent = n ? n + (n === 1 ? " day selected" : " days selected") : "";
      markMissing();
      if (!projectSel.value) {
        daysOpen.disabled = true;
        daysSummary.textContent = "Select project first…";
        return;
      }
      daysOpen.disabled = false;
      var labels = projectDays()
        .filter(function (d) { return committed.indexOf(d.id) >= 0; })
        .map(function (d) { return d.label; });
      daysSummary.textContent = labels.length ? labels[0] : "Select shooting day…";
    }

    function workflowUrl(id) {
      var u = new URL(window.location.href);
      u.search = "";
      u.searchParams.set("workflow_id", String(id));
      return u.toString();
    }

    function renderDays(keepChecked) {
      var pid = projectSel.value;
      var previously = keepChecked || checkedDayIds();
      list.innerHTML = "";
      setStartError("");
      if (!pid) {
        emptyMsg.hidden = false;
        emptyMsg.textContent = "Select project first…";
        addBtn.hidden = true;
        sep.hidden = true;
        hideNewDay();
        updateCount();
        return;
      }
      var days = daysByProject[pid] || daysByProject[String(pid)] || [];
      addBtn.hidden = false;
      sep.hidden = !days.length;
      emptyMsg.hidden = !!days.length;
      emptyMsg.textContent = "No shooting days yet — add one above.";
      days.forEach(function (d) {
        var row = document.createElement("label");
        row.className = "mr-mc__day-row" + (d.workflow_id ? " mr-mc__day-row--taken" : "");
        var label = document.createElement("span");
        label.className = "mr-mc__day-label";
        label.textContent = d.label;
        if (d.workflow_id) {
          row.appendChild(label);
          var open = document.createElement("a");
          open.className = "mr-mc__day-open" + (d.workflow_completed ? " mr-mc__day-open--done" : "");
          open.href = workflowUrl(d.workflow_id);
          open.textContent = d.workflow_completed ? "Completed" : "Open";
          row.appendChild(open);
        } else {
          var cb = document.createElement("input");
          cb.type = "radio";
          cb.name = "mr-wf-start-day";
          cb.value = d.id;
          cb.setAttribute("data-mr-wf-day", "");
          cb.checked = previously.indexOf(d.id) >= 0;
          cb.addEventListener("change", function () {
            setStartError("");
          });
          row.appendChild(cb);
          row.appendChild(label);
        }
        list.appendChild(row);
      });
      updateCount();
    }

    function newDayField(attr) {
      return newDay ? newDay.querySelector("[" + attr + "]") : null;
    }

    function setNewDayError(msg) {
      var el = newDayField("data-mr-wf-new-day-error");
      if (!el) return;
      el.textContent = msg || "";
      el.hidden = !msg;
    }

    var nameTouched = false;

    function suggestDayName(unit) {
      var days = daysByProject[projectSel.value] || daysByProject[String(projectSel.value)] || [];
      var best = 0;
      var width = 0;
      days.forEach(function (d) {
        if (Number(d.unit_number || 1) !== unit) return;
        var m = String(d.day_name || "").match(/(\d+)\s*$/);
        if (!m) return;
        var n = parseInt(m[1], 10);
        if (n > best) {
          best = n;
          width = m[1].length > 1 && m[1].charAt(0) === "0" ? m[1].length : 0;
        }
      });
      var next = String(best + 1);
      while (width && next.length < width) next = "0" + next;
      return next;
    }

    function applyDaySuggestion() {
      var nameEl = newDayField("data-mr-wf-new-day-name");
      var unitEl = newDayField("data-mr-wf-new-day-unit");
      if (!nameEl || nameTouched) return;
      var unit = parseInt(unitEl && unitEl.value, 10) || 1;
      nameEl.value = suggestDayName(unit);
    }

    function showNewDay() {
      if (!newDay) return;
      newDay.hidden = false;
      setNewDayError("");
      nameTouched = false;
      applyDaySuggestion();
      var dateEl = newDayField("data-mr-wf-new-day-date");
      if (dateEl && !dateEl.value) {
        var now = new Date();
        var pad = function (n) { return (n < 10 ? "0" : "") + n; };
        dateEl.value = now.getFullYear() + "-" + pad(now.getMonth() + 1) + "-" + pad(now.getDate());
      }
      var nameEl = newDayField("data-mr-wf-new-day-name");
      if (nameEl) {
        nameEl.focus();
        nameEl.select();
      }
    }

    function hideNewDay() {
      if (newDay) newDay.hidden = true;
    }

    projectSel.addEventListener("change", function () {
      committed = [];
      renderDays([]);
      finderState.note = "";
      renderShuttles();
      markMissing();
      hideNewDay();
    });
    addBtn.addEventListener("click", showNewDay);

    daysOpen.addEventListener("click", function () {
      renderDays(committed.slice());
      hideNewDay();
      if (typeof daysModal.showModal === "function") daysModal.showModal();
    });
    daysModal.querySelector("[data-mr-wf-days-done]").addEventListener("click", function () {
      committed = checkedDayIds().slice(0, 1);
      updateCount();
      daysModal.close();
    });
    daysModal.querySelector("[data-mr-wf-days-cancel]").addEventListener("click", function () {
      daysModal.close();
    });

    if (newDay) {
      var newDayName = newDayField("data-mr-wf-new-day-name");
      var newDayUnit = newDayField("data-mr-wf-new-day-unit");
      newDayName.addEventListener("input", function () {
        nameTouched = newDayName.value.trim() !== "";
      });
      newDayUnit.addEventListener("input", applyDaySuggestion);
      var newDayDate = newDayField("data-mr-wf-new-day-date");
      if (newDayDate && typeof newDayDate.showPicker === "function") {
        newDayDate.addEventListener("click", function () {
          try {
            newDayDate.showPicker();
          } catch (e) {
            // Browser may block showPicker outside a trusted click; the icon still works.
          }
        });
      }
      newDayField("data-mr-wf-new-day-cancel").addEventListener("click", hideNewDay);
      newDayField("data-mr-wf-new-day-save").addEventListener("click", function () {
        var pid = parseInt(projectSel.value, 10);
        postJson(newDay.getAttribute("data-url"), {
          project_id: pid,
          unit_number: parseInt(newDayField("data-mr-wf-new-day-unit").value, 10) || 1,
          day_name: newDayField("data-mr-wf-new-day-name").value.trim().replace(/^day\s*/i, ""),
          shooting_date: newDayField("data-mr-wf-new-day-date").value,
        }).then(function (res) {
          if (!res.ok) {
            setNewDayError((res.data && res.data.error) || "Could not add the shooting day.");
            return;
          }
          var d = res.data.day;
          var days = daysByProject[pid] || daysByProject[String(pid)] || [];
          if (!days.some(function (x) { return String(x.id) === String(d.id); })) {
            days.push(d);
            days.sort(function (a, b) {
              if (a.date !== b.date) return a.date < b.date ? -1 : 1;
              return a.id - b.id;
            });
          }
          daysByProject[String(pid)] = days;
          renderDays(d.workflow_id ? checkedDayIds() : [d.id]);
          hideNewDay();
          newDayField("data-mr-wf-new-day-name").value = "";
        });
      });
    }

    form.addEventListener("submit", function (ev) {
      ev.preventDefault();
      var ids = committed.slice();
      setStartError("");
      var firstMissing = markMissing(true);
      if (firstMissing) {
        if (!firstMissing.disabled) firstMissing.focus();
        return;
      }
      var notesEl = form.querySelector("[data-mr-wf-start-notes]");
      postJson(root.getAttribute("data-create-url"), {
        project_id: parseInt(projectSel.value, 10),
        shooting_day_ids: ids,
        shuttle_volume_id: selectedShuttle(),
        receive_notes: notesEl ? notesEl.value : "",
      }).then(function (res) {
        if (!res.ok) {
          setStartError((res.data && res.data.error) || "Could not start workflow.");
          return;
        }
        if (res.data.redirect) {
          window.location.href = res.data.redirect;
        } else {
          reloadWithWorkflow(res.data.workflow_id);
        }
      });
    });
  }

  function initActive(root) {
    var active = root.querySelector("[data-mr-wf-active]");
    if (!active) return;

    var receiveUrl = active.getAttribute("data-receive-url");
    var backupUrl = active.getAttribute("data-backup-url");
    var transcodeUrl = active.getAttribute("data-transcode-url");
    var completeUrl = active.getAttribute("data-complete-url");
    var issueUrl = active.getAttribute("data-issue-url");

    function afterOk(res) {
      if (!res.ok) {
        showError((res.data && res.data.error) || "Action blocked.");
        return;
      }
      if (res.data && res.data.note) {
        // Informational — not claiming automation
        console.info(res.data.note);
      }
      reloadPage();
    }

    active.querySelectorAll("[data-mr-wf-step]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var stage = btn.getAttribute("data-mr-wf-step");
        active.querySelectorAll("[data-mr-wf-panel]").forEach(function (panel) {
          panel.classList.toggle(
            "is-hidden",
            panel.getAttribute("data-mr-wf-panel") !== stage
          );
        });
        active.querySelectorAll("[data-mr-wf-step]").forEach(function (b) {
          b.classList.toggle("is-focus", b === btn);
        });
        var body = root.querySelector("[data-mr-wf-assistant-body]");
        var help = {
          receive: "Connect the Transfer / Shuttle drive and select today's shooting day.",
          backup: "Copy the material to Projects Backup. Do not move or delete files.",
          transcode: "Generate editing proxies and save them to In-house Storage.",
          complete: "Check the backup and proxies, then mark the day ready.",
        };
        if (body && help[stage]) body.textContent = help[stage];
      });
    });

    function checkedCardId(attr) {
      var checked = active.querySelector("[" + attr + "]:checked");
      return checked ? parseInt(checked.value, 10) : null;
    }

    var recvContinue = active.querySelector("[data-mr-wf-recv-continue]");
    if (recvContinue) {
      recvContinue.addEventListener("click", function () {
        postJson(receiveUrl, {
          action: "continue",
          shooting_day_ids: receiveDayIds(),
          shuttle_volume_id: selectedShuttleId(),
          receive_notes: (active.querySelector("[data-mr-wf-recv-notes]") || {}).value || "",
          checks: collectedChecks("[data-mr-wf-recv-check]"),
        }).then(afterOk);
      });
    }

    var GATE_BUTTONS = {
      receive_continue: "[data-mr-wf-recv-continue]",
      backup_start: "[data-mr-wf-backup-start]",
      backup_verify: "[data-mr-wf-backup-verify]",
      transcode_start: "[data-mr-wf-transcode-start]",
      transcode_verify: "[data-mr-wf-verify-open]",
      mark_ready: "[data-mr-wf-ready-open]",
    };

    function applyGates(res) {
      if (!res.ok) {
        showError((res.data && res.data.error) || "Could not save.");
        return;
      }
      var gates = res.data && res.data.workflow && res.data.workflow.gates;
      if (!gates) return;
      Object.keys(GATE_BUTTONS).forEach(function (key) {
        var btn = active.querySelector(GATE_BUTTONS[key]);
        var gate = gates[key];
        if (!btn || !gate) return;
        btn.disabled = !gate.ok;
        if (gate.ok) btn.removeAttribute("title");
        else btn.title = gate.error || "";
      });
    }

    function saveReceive(extra) {
      return postJson(
        receiveUrl,
        Object.assign({ action: "save" }, extra || {})
      ).then(applyGates);
    }

    function wireSaveChecks(checkSel, url, extra) {
      active.querySelectorAll(checkSel).forEach(function (cb) {
        cb.addEventListener("change", function () {
          var body = Object.assign({ action: "save" }, extra ? extra() : {});
          if (checkSel.indexOf("recv") >= 0 || checkSel.indexOf("backup") >= 0)
            body.checks = collectedChecks(checkSel);
          else if (checkSel.indexOf("pre-check") >= 0)
            body.pre_checks = collectedChecks(checkSel);
          else if (checkSel.indexOf("post-check") >= 0)
            body.post_checks = collectedChecks(checkSel);
          else if (checkSel.indexOf("complete") >= 0) body.checks = collectedChecks(checkSel);
          postJson(url, body).then(applyGates);
        });
      });
    }

    active.querySelectorAll(".mr-mc__vol-card input[type='radio']").forEach(function (input) {
      var card = input.closest(".mr-mc__vol-card");
      if (!card) return;
      card.addEventListener("pointerdown", function () {
        input.dataset.wasChecked = input.checked ? "1" : "";
      });
      input.addEventListener("click", function () {
        if (input.dataset.wasChecked !== "1" || input.hasAttribute("data-mr-wf-vol-locked")) return;
        input.dataset.wasChecked = "";
        input.checked = false;
        input.dispatchEvent(new Event("change", { bubbles: true }));
      });
    });

    var shuttleCards = active.querySelectorAll("[data-mr-wf-shuttle-card]");
    function selectedShuttleId() {
      return checkedCardId("data-mr-wf-shuttle-card");
    }
    var recvNotes = active.querySelector("[data-mr-wf-recv-notes]");

    function receiveDayIds() {
      return Array.prototype.map.call(
        active.querySelectorAll("[data-mr-wf-recv-day]:checked"),
        function (el) { return parseInt(el.value, 10); }
      );
    }

    var daysModal = active.querySelector("[data-mr-wf-days-modal]");
    var daysEdit = active.querySelector("[data-mr-wf-days-edit]");
    if (daysModal && daysEdit) {
      var daysError = daysModal.querySelector("[data-mr-wf-days-error]");
      var savedDayIds = receiveDayIds();

      var setDaysError = function (msg) {
        daysError.textContent = msg || "";
        daysError.hidden = !msg;
      };
      var restoreTicks = function () {
        daysModal.querySelectorAll("[data-mr-wf-recv-day]").forEach(function (cb) {
          cb.checked = savedDayIds.indexOf(parseInt(cb.value, 10)) >= 0;
        });
      };
      daysEdit.addEventListener("click", function () {
        restoreTicks();
        setDaysError("");
        if (typeof daysModal.showModal === "function") daysModal.showModal();
      });
      daysModal.querySelector("[data-mr-wf-days-cancel]").addEventListener("click", function () {
        restoreTicks();
        daysModal.close();
      });
      daysModal.querySelector("[data-mr-wf-days-save]").addEventListener("click", function () {
        var ids = receiveDayIds();
        if (!ids.length) {
          setDaysError("A workflow needs at least one shooting day.");
          return;
        }
        postJson(receiveUrl, { action: "save", shooting_day_ids: ids }).then(function (res) {
          if (!res.ok) {
            setDaysError((res.data && res.data.error) || "Could not update shooting days.");
            return;
          }
          var wfData = res.data.workflow || {};
          if (wfData.current_stage && wfData.current_stage !== active.getAttribute("data-stage")) {
            reloadPage();
            return;
          }
          savedDayIds = ids;
          var head = root.querySelector(".mr-mc__active-day");
          if (head && wfData.shooting_day_label) head.textContent = wfData.shooting_day_label;
          applyGates(res);
          daysModal.close();
        });
      });
    }
    shuttleCards.forEach(function (card) {
      card.addEventListener("change", function () {
        saveReceive({ shuttle_volume_id: selectedShuttleId() });
      });
    });
    if (recvNotes) {
      recvNotes.addEventListener("change", function () {
        saveReceive({ receive_notes: recvNotes.value || "" });
      });
    }
    wireSaveChecks("[data-mr-wf-recv-check]", receiveUrl);
    wireSaveChecks("[data-mr-wf-pre-check]", transcodeUrl);
    wireSaveChecks("[data-mr-wf-post-check]", transcodeUrl);
    wireSaveChecks("[data-mr-wf-complete-check]", completeUrl);

    active.querySelectorAll("[data-mr-wf-backup-dest]").forEach(function (card) {
      card.addEventListener("change", function () {
        postJson(backupUrl, {
          action: "save",
          backup_destination_id: checkedCardId("data-mr-wf-backup-dest"),
        }).then(function (res) {
          applyGates(res);
          var detail = res.ok && res.data && res.data.workflow;
          if (!detail) return;
          var pathInput = active.querySelector("[data-mr-wf-copy-modal] [data-mr-wf-copy-path]");
          if (pathInput && !pathInput.dataset.touched) {
            pathInput.value = (detail.backup_copy && detail.backup_copy.destination_path) || "";
          }
          var name = (detail.backup_destination && detail.backup_destination.name) || "—";
          active.querySelectorAll(
            "[data-mr-wf-copy-dest-name], [data-mr-wf-panel='backup'] .mr-mc__flow-box--dst em"
          ).forEach(function (el) { el.textContent = name; });
        });
      });
    });

    var confirmModal = root.querySelector("[data-mr-wf-confirm-modal]");
    var pendingFinish = null;

    function confirmChecksFor(kind) {
      return confirmModal ? confirmModal.querySelector('[data-mr-wf-confirm-checks="' + kind + '"]') : null;
    }

    function checkedIn(kind) {
      var set = confirmChecksFor(kind);
      if (!set) return [];
      return Array.prototype.filter.call(set.querySelectorAll("[data-mr-wf-confirm-check]"), function (b) {
        return b.checked;
      }).map(function (b) { return b.value; });
    }

    var confirmProgressed = false;

    function confirmFinish(url, payload, kind) {
      if (!confirmModal) return;
      var isCopy = kind === "copy";
      pendingFinish = {url: url, payload: payload, kind: kind};
      confirmProgressed = false;
      confirmModal.querySelector("[data-mr-wf-confirm-title]").textContent = isCopy ? "Copy finished" : "Transcoding finished";
      confirmModal.querySelector("[data-mr-wf-confirm-description]").textContent = isCopy
        ? "Check the copied original media. Verifying now moves the workflow straight to Transcode."
        : "Check the generated proxies. Verifying now hands the shooting day over to editing.";
      var shown = isCopy ? ["copy"] : ["transcode", "final"];
      confirmModal.querySelectorAll("[data-mr-wf-confirm-checks]").forEach(function (set) {
        set.hidden = shown.indexOf(set.getAttribute("data-mr-wf-confirm-checks")) < 0;
      });
      confirmModal.querySelector("[data-mr-wf-confirm-next]").hidden = !isCopy;
      confirmModal.querySelector("[data-mr-wf-confirm-failed]").hidden = !isCopy;
      confirmModal.querySelector("[data-mr-wf-confirm-primary]").textContent = isCopy
        ? "Copy finished & verified"
        : "Finished — ready for editing";
      confirmModal.querySelector("[data-mr-wf-confirm-error]").hidden = true;
      confirmModal.showModal();
    }

    function runSteps(steps) {
      return steps.reduce(function (chain, step) {
        return chain.then(function (res) {
          if (res && !res.ok) return res;
          return postJson(step.url, step.body).then(function (next) {
            if (next.ok) confirmProgressed = true;
            return next;
          });
        });
      }, Promise.resolve(null));
    }

    if (confirmModal) {
      confirmModal.querySelector("form").addEventListener("submit", function (event) {
        event.preventDefault();
        var choice = event.submitter ? event.submitter.value : "verified";
        if (choice === "cancel") {
          confirmModal.close();
          return;
        }
        if (!pendingFinish) return;
        var buttons = confirmModal.querySelectorAll(".mr-mc__actions-row button");
        if (buttons[0].disabled) return;
        buttons.forEach(function (b) { b.disabled = true; });
        var finish = pendingFinish;
        var isCopy = finish.kind === "copy";
        var steps = [];
        if (isCopy) {
          var backupChecks = checkedIn("copy");
          steps.push({ url: finish.url, body: Object.assign({}, finish.payload, { checks: backupChecks }) });
          if (choice === "verified") {
            steps.push({ url: finish.url, body: { action: "verify", checks: backupChecks, verification_method: "operator_confirmed" } });
          } else if (choice === "failed") {
            steps.push({ url: finish.url, body: { action: "fail_verify" } });
          }
        } else {
          var postChecks = checkedIn("transcode");
          var finalChecks = checkedIn("final");
          steps.push({ url: finish.url, body: Object.assign({}, finish.payload, { post_checks: postChecks }) });
          if (choice === "verified") {
            steps.push({ url: finish.url, body: { action: "verify", post_checks: postChecks } });
            steps.push({ url: completeUrl, body: { action: "mark_ready", checks: finalChecks } });
          }
        }
        var openTranscode = isCopy && choice === "verified"
          && confirmModal.querySelector("[data-mr-wf-confirm-start-transcode]").checked;
        runSteps(steps).then(function (res) {
          if (res && res.ok) {
            confirmProgressed = false;
            confirmModal.close();
            if (openTranscode) {
              var u = new URL(window.location.href);
              u.searchParams.set("open", "transcode");
              window.location.href = u.toString();
              return;
            }
            afterOk(res);
            return;
          }
          var error = confirmModal.querySelector("[data-mr-wf-confirm-error]");
          error.textContent = (res && res.data && res.data.error) || "Could not record completion.";
          error.hidden = false;
        }).catch(function () {
          var error = confirmModal.querySelector("[data-mr-wf-confirm-error]");
          error.textContent = "Connection lost. Close and reopen the workflow to check whether completion was saved.";
          error.hidden = false;
        }).finally(function () {
          buttons.forEach(function (b) { b.disabled = false; });
        });
      });
      confirmModal.addEventListener("close", function () {
        pendingFinish = null;
        if (confirmProgressed) reloadPage();
      });
    }

    function clickAction(sel, url, payloadFn) {
      var el = active.querySelector(sel);
      if (!el) return;
      el.addEventListener("click", function () {
        var payload = payloadFn();
        if (payload.action === "finish_copy" || payload.action === "finish") {
          confirmFinish(url, payload, payload.action === "finish_copy" ? "copy" : "transcode");
          return;
        }
        el.disabled = true;
        postJson(url, payload).then(afterOk).catch(function () {
          showError("Could not save. Please try again.");
        }).finally(function () { el.disabled = false; });
      });
    }

    var estRoot = active.querySelector("[data-mr-wf-backup-estimate]");
    var savedEstimate = estRoot ? parseInt(estRoot.getAttribute("data-initial-minutes"), 10) || 0 : 0;
    var estimateTimer = null;
    function backupEstimateMinutes() {
      if (!estRoot || !window.Dts) return null;
      var total = window.Dts.getTotalMinutes(estRoot);
      return isFinite(total) ? total : null;
    }
    function showEstimate() {
      if (estRoot && window.Dts) window.Dts.setTotalMinutes(estRoot, savedEstimate);
    }
    if (estRoot && window.Dts) {
      window.Dts.init(estRoot);
      estRoot.addEventListener("dts:change", function () {
        window.clearTimeout(estimateTimer);
        estimateTimer = window.setTimeout(function () {
          var total = backupEstimateMinutes();
          if (total !== null) savedEstimate = total;
        }, 150);
      });
    }

    var openPathUrl = active.getAttribute("data-open-path-url") || "";
    active.addEventListener("click", function (ev) {
      var btn = ev.target.closest ? ev.target.closest("[data-mr-wf-open-path]") : null;
      if (!btn || !openPathUrl) return;
      var path = (btn.getAttribute("data-mr-wf-open-path") || "").trim();
      if (!path) return;
      btn.disabled = true;

      function parentOf(p) {
        var parts = p.replace(/\/+$/, "").split("/");
        if (parts.length <= 3) return "";
        return parts.slice(0, -1).join("/");
      }

      function tryOpen(target) {
        return fetch(openPathUrl + "?path=" + encodeURIComponent(target), {
          credentials: "same-origin",
          headers: { Accept: "application/json" },
        })
          .then(function (r) { return r.json(); })
          .then(function (data) {
            if (!data.ok && /does not exist/i.test(data.error || "") && parentOf(target)) {
              return tryOpen(parentOf(target));
            }
            if (!data.ok) {
              showError(data.error || "Could not open in Finder.");
              return;
            }
            if (data.path && !data.opened) {
              if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(data.path);
              showError(data.message || "Path copied — open in Finder isn't available on this server.");
              return;
            }
            if (target !== path) {
              showError(path + " doesn't exist yet — opened " + target + " instead.");
            }
          });
      }

      tryOpen(path)
        .catch(function () { showError("Could not open in Finder."); })
        .finally(function () { btn.disabled = false; });
    });

    var DEST_PATH_KEY = "mr-hdd-dest-path:v";

    function rememberedDestPath(volId) {
      if (!volId) return "";
      try {
        return (window.localStorage.getItem(DEST_PATH_KEY + volId) || "").trim();
      } catch (e) {
        return "";
      }
    }

    function saveDestPath(volId, path) {
      if (!volId || !path) return;
      try {
        window.localStorage.setItem(DEST_PATH_KEY + volId, path);
      } catch (e) {
        // Storage unavailable — the path is still filled in for this copy.
      }
    }

    function initCopyBrowse(modal, pathInput, setPathHint, cardAttr) {
      var btn = modal.querySelector("[data-mr-wf-copy-browse]");
      var dlg = modal.querySelector("[data-mr-wf-browse-modal]");
      if (!btn || !dlg || !pathInput) return;
      var list = dlg.querySelector("[data-mr-wf-browse-list]");
      var current = dlg.querySelector("[data-mr-wf-browse-current]");
      var upBtn = dlg.querySelector("[data-mr-wf-browse-up]");
      var selectBtn = dlg.querySelector("[data-mr-wf-browse-select]");
      var loading = dlg.querySelector("[data-mr-wf-browse-loading]");
      var empty = dlg.querySelector("[data-mr-wf-browse-empty]");
      var error = dlg.querySelector("[data-mr-wf-browse-error]");
      var state = { volId: null, rel: "", abs: "", parent: "" };

      function showError(msg) {
        error.textContent = msg || "";
        error.hidden = !msg;
      }

      function load(rel, absHint) {
        list.innerHTML = "";
        empty.hidden = true;
        current.textContent = "Loading…";
        selectBtn.disabled = true;
        upBtn.disabled = true;
        showError("");
        loading.hidden = false;
        var url = "/machine-room/volumes/" + encodeURIComponent(state.volId) +
          "/browse?path=" + encodeURIComponent(rel || "");
        if (absHint) url += "&absolute=" + encodeURIComponent(absHint);
        fetch(url, {
          credentials: "same-origin",
          headers: { Accept: "application/json", "X-Requested-With": "XMLHttpRequest" },
        })
          .then(function (r) {
            return r.json().catch(function () {
              return { ok: false, error: "Server error (HTTP " + r.status + ")." };
            });
          })
          .catch(function () {
            return { ok: false, error: "Could not load folders. Check that the volume is mounted." };
          })
          .then(function (data) {
            loading.hidden = true;
            if (!data || !data.ok) {
              current.textContent = "—";
              showError((data && data.error) || "Browse failed.");
              return;
            }
            state.rel = data.relative_path || "";
            state.abs = data.absolute_path || "";
            state.parent = data.parent_path || "";
            current.textContent = state.abs || "—";
            selectBtn.disabled = !state.abs;
            upBtn.disabled = !state.rel;
            var folders = data.folders || [];
            empty.hidden = folders.length > 0;
            folders.forEach(function (folder) {
              var li = document.createElement("li");
              var b = document.createElement("button");
              b.type = "button";
              b.textContent = folder.name;
              b.addEventListener("click", function () { load(folder.path); });
              li.appendChild(b);
              list.appendChild(li);
            });
          });
      }

      btn.addEventListener("click", function () {
        state.volId = checkedCardId(cardAttr);
        if (!state.volId) {
          setPathHint("Select a destination volume first.");
          return;
        }
        if (typeof dlg.showModal === "function") dlg.showModal();
        load("", (pathInput.value || "").trim() || undefined);
      });
      upBtn.addEventListener("click", function () { load(state.parent || ""); });
      dlg.querySelector("[data-mr-wf-browse-cancel]").addEventListener("click", function () {
        dlg.close();
      });
      selectBtn.addEventListener("click", function () {
        if (!state.abs) return;
        pathInput.value = state.abs;
        pathInput.dataset.touched = "1";
        saveDestPath(state.volId, state.abs);
        setPathHint("Selected folder (remembered for next time)");
        dlg.close();
        pathInput.focus();
      });
    }

    var copyModal = active.querySelector("[data-mr-wf-copy-modal]");
    var copyOpen = active.querySelector("[data-mr-wf-backup-start]");
    if (copyModal && copyOpen) {
      var copyForm = copyModal.querySelector("[data-mr-wf-copy-form]");
      var copyError = copyModal.querySelector("[data-mr-wf-copy-error]");
      var setCopyError = function (msg) {
        copyError.textContent = msg || "";
        copyError.hidden = !msg;
      };
      var copyPath = copyModal.querySelector("[data-mr-wf-copy-path]");
      var copyPathHint = copyModal.querySelector("[data-mr-wf-copy-path-hint]");
      var setPathHint = function (msg) {
        if (!copyPathHint) return;
        copyPathHint.textContent = msg || "";
        copyPathHint.hidden = !msg;
      };
      if (copyPath) {
        copyPath.addEventListener("input", function () {
          copyPath.dataset.touched = "1";
          setPathHint("");
        });
      }
      initCopyBrowse(copyModal, copyPath, setPathHint, "data-mr-wf-backup-dest");
      copyOpen.addEventListener("click", function () {
        setCopyError("");
        var volId = checkedCardId("data-mr-wf-backup-dest");
        var remembered = rememberedDestPath(volId);
        if (copyPath && !copyPath.dataset.touched && remembered) {
          copyPath.value = remembered;
          setPathHint("Restored last selected folder on this volume");
        }
        if (typeof copyModal.showModal === "function") copyModal.showModal();
        showEstimate();
      });
      copyForm.addEventListener("submit", function (ev) {
        if (ev.submitter && ev.submitter.value === "cancel") return;
        ev.preventDefault();
        var total = backupEstimateMinutes();
        if (!total) {
          setCopyError("Set the estimated copy time.");
          return;
        }
        var fd = new FormData(copyForm);
        var submitBtn = ev.submitter;
        if (submitBtn) submitBtn.disabled = true;
        postJson(backupUrl, {
          action: "start",
          backup_estimated_minutes: total,
          backup_destination_id: checkedCardId("data-mr-wf-backup-dest"),
          video_size_tb: fd.get("video_size_tb"),
          audio_size_gb: fd.get("audio_size_gb"),
          destination_path: fd.get("destination_path"),
          checksum_method: fd.get("checksum_method"),
          checksum_status: fd.get("checksum_status"),
          notes: fd.get("notes"),
          make_critical: fd.get("make_critical") === "1",
        }).then(function (res) {
          if (submitBtn) submitBtn.disabled = false;
          if (!res.ok) {
            setCopyError((res.data && res.data.error) || "Could not start the copy.");
            return;
          }
          copyModal.close();
          afterOk(res);
        }).catch(function () {
          if (submitBtn) submitBtn.disabled = false;
          setCopyError("Could not save. Please try again.");
        });
      });
    }
    clickAction("[data-mr-wf-backup-finish]", backupUrl, function () {
      return { action: "finish_copy" };
    });
    clickAction("[data-mr-wf-backup-verify]", backupUrl, function () {
      return { action: "verify", verification_method: "operator_confirmed" };
    });
    clickAction("[data-mr-wf-backup-fail]", backupUrl, function () {
      return { action: "fail_verify" };
    });

    var tModal = active.querySelector("[data-mr-wf-transcode-modal]");
    var tPath = tModal ? tModal.querySelector("[data-mr-wf-copy-path]") : null;

    function saveTranscodeTarget() {
      postJson(transcodeUrl, {
        action: "save",
        proxy_destination_id: checkedCardId("data-mr-wf-proxy-dest"),
      }).then(function (res) {
        applyGates(res);
        var detail = res.ok && res.data && res.data.workflow;
        if (!detail || !tModal) return;
        if (tPath && !tPath.dataset.touched) tPath.value = detail.proxy_destination_path || "";
        var name = (detail.proxy_destination && detail.proxy_destination.name) || "—";
        active.querySelectorAll(
          "[data-mr-wf-transcode-dest-name], [data-mr-wf-panel='transcode'] .mr-mc__flow-box--dst em"
        ).forEach(function (el) { el.textContent = name; });
      });
    }
    active.querySelectorAll("[data-mr-wf-proxy-dest]").forEach(function (card) {
      card.addEventListener("change", saveTranscodeTarget);
    });

    var tOpen = active.querySelector("[data-mr-wf-transcode-start]");
    if (tModal && tOpen) {
      var tForm = tModal.querySelector("[data-mr-wf-transcode-form]");
      var tError = tModal.querySelector("[data-mr-wf-transcode-error]");
      var tHint = tModal.querySelector("[data-mr-wf-copy-path-hint]");
      var tEst = tModal.querySelector("[data-mr-wf-transcode-estimate]");
      var tSavedEst = tEst ? parseInt(tEst.getAttribute("data-initial-minutes"), 10) || 0 : 0;
      var setTError = function (msg) {
        tError.textContent = msg || "";
        tError.hidden = !msg;
      };
      var setTHint = function (msg) {
        if (!tHint) return;
        tHint.textContent = msg || "";
        tHint.hidden = !msg;
      };
      var tEstimate = function () {
        if (!tEst || !window.Dts) return null;
        var total = window.Dts.getTotalMinutes(tEst);
        return isFinite(total) ? total : null;
      };
      if (tEst && window.Dts) {
        window.Dts.init(tEst);
        tEst.addEventListener("dts:change", function () {
          var total = tEstimate();
          if (total !== null) tSavedEst = total;
        });
      }
      if (tPath) {
        tPath.addEventListener("input", function () {
          tPath.dataset.touched = "1";
          setTHint("");
        });
      }
      initCopyBrowse(tModal, tPath, setTHint, "data-mr-wf-proxy-dest");
      var tPreset = tModal.querySelector("[data-mr-wf-preset]");
      var tPresetDefault = tModal.querySelector("[data-mr-wf-preset-default]");
      var presetKey = "mr-proxy-preset-default:p" + (active.getAttribute("data-project-id") || "0");
      var defaultPreset = function () {
        try {
          return window.localStorage.getItem(presetKey) || "";
        } catch (e) {
          return "";
        }
      };
      var syncPresetDefault = function () {
        if (!tPreset || !tPresetDefault) return;
        var isDefault = !!tPreset.value && tPreset.value === defaultPreset();
        tPresetDefault.disabled = !tPreset.value || isDefault;
        tPresetDefault.textContent = isDefault ? "Default" : "Set as default";
      };
      if (tPreset && tPresetDefault) {
        tPreset.addEventListener("change", syncPresetDefault);
        tPresetDefault.addEventListener("click", function () {
          try {
            window.localStorage.setItem(presetKey, tPreset.value);
          } catch (e) {
            showError("Could not save the default preset in this browser.");
          }
          syncPresetDefault();
        });
      }
      tOpen.addEventListener("click", function () {
        setTError("");
        if (tPreset && !tPreset.value && !tPreset.dataset.chosen) {
          var preferred = defaultPreset();
          if (preferred && tPreset.querySelector('option[value="' + CSS.escape(preferred) + '"]')) {
            tPreset.value = preferred;
          }
        }
        syncPresetDefault();
        var remembered = rememberedDestPath(checkedCardId("data-mr-wf-proxy-dest"));
        if (tPath && tPath.dataset.fromDay === "1" && !tPath.dataset.touched) {
          setTHint("Proxy location set when this shooting day was added");
        } else if (tPath && !tPath.dataset.touched && remembered) {
          tPath.value = remembered;
          setTHint("Restored last selected folder on this volume");
        }
        if (typeof tModal.showModal === "function") tModal.showModal();
        if (tEst && window.Dts) window.Dts.setTotalMinutes(tEst, tSavedEst);
      });
      var pageUrl = new URL(window.location.href);
      if (pageUrl.searchParams.get("open") === "transcode") {
        pageUrl.searchParams.delete("open");
        window.history.replaceState(null, "", pageUrl.toString());
        if (!tOpen.disabled) tOpen.click();
      }
      tForm.addEventListener("submit", function (ev) {
        if (ev.submitter && ev.submitter.value === "cancel") return;
        ev.preventDefault();
        var total = tEstimate();
        if (!total) {
          setTError("Set the estimated transcoding time.");
          return;
        }
        var fd = new FormData(tForm);
        var submitBtn = ev.submitter;
        if (submitBtn) submitBtn.disabled = true;
        postJson(transcodeUrl, {
          action: "start",
          proxy_destination_id: checkedCardId("data-mr-wf-proxy-dest"),
          proxy_preset: fd.get("proxy_preset") || "",
          pre_checks: collectedChecks("[data-mr-wf-pre-check]"),
          transcode_estimated_minutes: total,
          destination_path: fd.get("destination_path"),
          notes: fd.get("notes"),
        }).then(function (res) {
          if (submitBtn) submitBtn.disabled = false;
          if (!res.ok) {
            setTError((res.data && res.data.error) || "Could not start transcoding.");
            return;
          }
          tModal.close();
          afterOk(res);
        }).catch(function () {
          if (submitBtn) submitBtn.disabled = false;
          setTError("Could not save. Please try again.");
        });
      });
    }
    clickAction("[data-mr-wf-transcode-finish]", transcodeUrl, function () {
      return { action: "finish" };
    });
    clickAction("[data-mr-wf-backup-pause]", backupUrl, function () { return { action: "pause" }; });
    clickAction("[data-mr-wf-backup-resume]", backupUrl, function () { return { action: "resume" }; });
    clickAction("[data-mr-wf-transcode-pause]", transcodeUrl, function () { return { action: "pause" }; });
    clickAction("[data-mr-wf-transcode-resume]", transcodeUrl, function () { return { action: "resume" }; });
    function checklistModal(openSel, modalSel, url, payloadFn, failMsg) {
      var dlg = active.querySelector(modalSel);
      var opener = active.querySelector(openSel);
      if (!dlg || !opener) return;
      var errEl = dlg.querySelector("[data-mr-wf-checks-error]");
      opener.addEventListener("click", function () {
        errEl.hidden = true;
        if (typeof dlg.showModal === "function") dlg.showModal();
      });
      dlg.querySelector("[data-mr-wf-checks-form]").addEventListener("submit", function (ev) {
        if (ev.submitter && ev.submitter.value === "cancel") return;
        ev.preventDefault();
        var btn = ev.submitter;
        if (btn) btn.disabled = true;
        var steps = payloadFn();
        if (!Array.isArray(steps)) steps = [{ url: url, body: steps }];
        var progressed = false;
        steps.reduce(function (chain, step) {
          return chain.then(function (res) {
            if (res && !res.ok) return res;
            return postJson(step.url, step.body).then(function (next) {
              if (next.ok) progressed = true;
              return next;
            });
          });
        }, Promise.resolve(null)).then(function (res) {
          if (!res.ok) {
            errEl.textContent = (res.data && res.data.error) || failMsg;
            errEl.hidden = false;
            if (progressed) dlg.addEventListener("close", reloadPage, { once: true });
            return;
          }
          dlg.close();
          afterOk(res);
        }).catch(function () {
          errEl.textContent = "Could not save. Please try again.";
          errEl.hidden = false;
        }).finally(function () {
          if (btn) btn.disabled = false;
        });
      });
    }
    checklistModal("[data-mr-wf-verify-open]", "[data-mr-wf-verify-modal]", transcodeUrl, function () {
      return [
        { url: transcodeUrl, body: { action: "verify", post_checks: collectedChecks("[data-mr-wf-post-check]") } },
        { url: completeUrl, body: { action: "mark_ready", checks: collectedChecks("[data-mr-wf-verify-final-check]") } },
      ];
    }, "Could not verify proxies.");
    checklistModal("[data-mr-wf-ready-open]", "[data-mr-wf-ready-modal]", completeUrl, function () {
      return { action: "mark_ready", checks: collectedChecks("[data-mr-wf-complete-check]") };
    }, "Could not mark ready for editing.");

    var modal = root.querySelector("[data-mr-wf-problem-modal]");
    var openProb = active.querySelector("[data-mr-wf-open-problem]");
    if (modal && openProb) {
      openProb.addEventListener("click", function () {
        if (typeof modal.showModal === "function") modal.showModal();
      });
      var probForm = modal.querySelector("[data-mr-wf-problem-form]");
      if (probForm) {
        probForm.addEventListener("submit", function (ev) {
          var submitter = ev.submitter;
          if (submitter && submitter.value === "cancel") return;
          ev.preventDefault();
          var fd = new FormData(probForm);
          postJson(issueUrl, {
            category: fd.get("category"),
            description: fd.get("description"),
          }).then(function (res) {
            if (typeof modal.close === "function") modal.close();
            afterOk(res);
          });
        });
      }
    }

    active.querySelectorAll("[data-mr-wf-resolve-issue]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var note = window.prompt("Resolution note (required):");
        if (!note) return;
        postJson(btn.getAttribute("data-url"), { resolution_note: note }).then(afterOk);
      });
    });

    var endModal = active.querySelector("[data-mr-wf-end-modal]");
    var openEnd = active.querySelector("[data-mr-wf-open-end]");
    if (endModal && openEnd) {
      var endForm = endModal.querySelector("[data-mr-wf-end-form]");
      var endError = endModal.querySelector("[data-mr-wf-end-error]");
      openEnd.addEventListener("click", function () {
        endError.hidden = true;
        if (typeof endModal.showModal === "function") endModal.showModal();
      });
      endForm.addEventListener("submit", function (ev) {
        if (ev.submitter && ev.submitter.value === "cancel") return;
        ev.preventDefault();
        var reason = (new FormData(endForm).get("reason") || "").trim();
        if (!reason) {
          endError.textContent = "Write a short reason first.";
          endError.hidden = false;
          return;
        }
        postJson(endModal.getAttribute("data-url"), { reason: reason }).then(function (res) {
          if (!res.ok) {
            endError.textContent = (res.data && res.data.error) || "Could not end the workflow.";
            endError.hidden = false;
            return;
          }
          reloadPage();
        });
      });
    }

    var resumeBtn = active.querySelector("[data-mr-wf-resume]");
    if (resumeBtn) {
      resumeBtn.addEventListener("click", function () {
        postJson(resumeBtn.getAttribute("data-url"), {}).then(afterOk);
      });
    }

    var reopen = active.querySelector("[data-mr-wf-reopen]");
    if (reopen) {
      reopen.addEventListener("click", function () {
        var reason = window.prompt("Reason to reopen (required):");
        if (!reason) return;
        postJson(reopen.getAttribute("data-url"), {
          reason: reason,
          stage: "receive",
        }).then(afterOk);
      });
    }
  }

  function initAssistant(root) {
    var modal = root.querySelector("[data-mr-wf-assistant]");
    var trigger = root.querySelector("[data-mr-wf-assistant-open]");
    if (!modal || !trigger) return;
    trigger.addEventListener("click", function () {
      if (typeof modal.showModal === "function") modal.showModal();
    });
    modal.addEventListener("click", function (ev) {
      if (ev.target === modal) modal.close();
    });
  }

  function initCardActions(root) {
    var modal = root.querySelector("[data-mr-wf-card-end-modal]");
    if (modal) {
      var form = modal.querySelector("[data-mr-wf-card-end-form]");
      var title = modal.querySelector("[data-mr-wf-card-end-title]");
      var error = modal.querySelector("[data-mr-wf-card-end-error]");
      var endUrl = "";
      root.querySelectorAll("[data-mr-wf-card-end]").forEach(function (btn) {
        btn.addEventListener("click", function () {
          endUrl = btn.getAttribute("data-url");
          title.textContent = "End workflow at " + (btn.getAttribute("data-stage") || "this step");
          form.reset();
          error.hidden = true;
          if (typeof modal.showModal === "function") modal.showModal();
        });
      });
      form.addEventListener("submit", function (ev) {
        if (ev.submitter && ev.submitter.value === "cancel") return;
        ev.preventDefault();
        var reason = (new FormData(form).get("reason") || "").trim();
        if (!reason) {
          error.textContent = "Write a short reason first.";
          error.hidden = false;
          return;
        }
        postJson(endUrl, { reason: reason }).then(function (res) {
          if (!res.ok) {
            error.textContent = (res.data && res.data.error) || "Could not end the workflow.";
            error.hidden = false;
            return;
          }
          reloadPage();
        });
      });
    }
    root.querySelectorAll("[data-mr-wf-card-resume]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        postJson(btn.getAttribute("data-url"), {}).then(function (res) {
          if (!res.ok) {
            showError((res.data && res.data.error) || "Could not resume the workflow.");
            return;
          }
          reloadPage();
        });
      });
    });
  }

  function initOperationClocks(root) {
    function duration(ms) {
      var minutes = Math.floor(Math.max(0, ms) / 60000);
      return Math.floor(minutes / 60) + "h " + (minutes % 60) + "m";
    }
    function update() {
      root.querySelectorAll("[data-mr-wf-clock]").forEach(function (node) {
        var start = Number(node.dataset.startedMs);
        var finish = Number(node.dataset.finishedMs);
        var stopped = node.dataset.stopped === "1";
        if (!start) return;
        node.querySelector("[data-mr-wf-elapsed]").textContent = stopped && !finish ? "Stopped — see activity history" : duration((finish || Date.now()) - start);
        var remaining = node.querySelector("[data-mr-wf-remaining]");
        var estimate = Number(node.dataset.estimateMin);
        if (finish) remaining.textContent = "Finished";
        else if (stopped) remaining.textContent = "Stopped";
        else if (estimate) {
          var left = start + estimate * 60000 - Date.now();
          remaining.textContent = left > 0 ? "About " + Math.ceil(left / 60000) + " min" : "Estimate exceeded · still running";
        }
      });
    }
    update();
    if (root.querySelector("[data-mr-wf-clock]")) window.setInterval(update, 10000);
  }

  function initFinishAlarm(root) {
    var active = root.querySelector("[data-mr-wf-active]");
    if (!active) return;

    var BEEP_EVERY_MS = 3000;
    var baseTitle = document.title;
    var audioCtx = null;
    var lastBeep = 0;
    var flash = false;

    function ctx() {
      if (audioCtx) return audioCtx;
      var Ctor = window.AudioContext || window.webkitAudioContext;
      if (!Ctor) return null;
      try {
        audioCtx = new Ctor();
      } catch (e) {
        audioCtx = null;
      }
      return audioCtx;
    }

    function unlockAudio() {
      var c = ctx();
      if (c && c.state === "suspended") c.resume().catch(function () {});
    }
    ["pointerdown", "keydown"].forEach(function (ev) {
      document.addEventListener(ev, unlockAudio, { capture: true });
    });

    function beep() {
      var c = ctx();
      if (!c || c.state !== "running") return false;
      var t = c.currentTime;
      [0, 0.22, 0.44].forEach(function (offset, i) {
        var osc = c.createOscillator();
        var gain = c.createGain();
        osc.type = "square";
        osc.frequency.value = i === 2 ? 1320 : 880;
        gain.gain.setValueAtTime(0.0001, t + offset);
        gain.gain.exponentialRampToValueAtTime(0.18, t + offset + 0.02);
        gain.gain.exponentialRampToValueAtTime(0.0001, t + offset + 0.18);
        osc.connect(gain).connect(c.destination);
        osc.start(t + offset);
        osc.stop(t + offset + 0.2);
      });
      return true;
    }

    function isDue(box) {
      if ((box.getAttribute("data-status") || "").trim() !== "in_progress") return false;
      if (!box.querySelector(".mr-mc__finish-btn")) return false;
      var snap = window.__tmTaskCopyLiveProgress && window.__tmTaskCopyLiveProgress(box);
      if (snap) return snap.isOver;
      var est = parseInt(box.getAttribute("data-est-min"), 10);
      var started = parseInt(box.getAttribute("data-started-ms"), 10) || 0;
      return !!(started && est > 0 && Date.now() >= started + est * 60000);
    }

    function message(box) {
      var msg = box.querySelector("[data-mr-wf-alarm-msg]");
      if (!msg) {
        msg = document.createElement("p");
        msg.className = "mr-mc__alarm-msg";
        msg.setAttribute("role", "alert");
        msg.setAttribute("data-mr-wf-alarm-msg", "");
        var actions = box.querySelector(".task-copy-live-actions");
        box.insertBefore(msg, actions || null);
      }
      return msg;
    }

    function tick() {
      var boxes = Array.prototype.slice.call(active.querySelectorAll(".mr-mc__copy-live"));
      var due = boxes.filter(isDue);
      var silent = !!document.querySelector("dialog[open]");
      var c = audioCtx;
      var soundBlocked = !c || c.state !== "running";
      active.querySelectorAll(".mr-mc__step.is-alarming").forEach(function (b) {
        b.classList.remove("is-alarming");
      });
      boxes.forEach(function (box) {
        var on = due.indexOf(box) >= 0;
        box.classList.toggle("is-alarming", on);
        var panel = box.closest("[data-mr-wf-panel]");
        var stage = panel && panel.getAttribute("data-mr-wf-panel");
        var stepBtn = stage && active.querySelector('[data-mr-wf-step="' + stage + '"]');
        if (stepBtn && on) stepBtn.classList.add("is-alarming");
        var existing = box.querySelector("[data-mr-wf-alarm-msg]");
        if (!on) {
          if (existing) existing.remove();
          return;
        }
        var finishLabel = (box.querySelector(".mr-mc__finish-btn").textContent || "Finish").trim();
        message(box).textContent = "Estimated time is up. Click “" + finishLabel + "” to stop the alarm."
          + (soundBlocked ? " Click anywhere on the page to turn the alarm sound on." : "");
      });
      if (!due.length) {
        document.title = baseTitle;
        return;
      }
      flash = !flash;
      document.title = flash ? "⏰ Time is up · " + baseTitle : baseTitle;
      if (silent) return;
      var now = Date.now();
      if (now - lastBeep >= BEEP_EVERY_MS) {
        unlockAudio();
        if (beep()) lastBeep = now;
      }
    }

    tick();
    window.setInterval(tick, 1000);
  }

  function initCreateModal(root) {
    var modal = root.querySelector("[data-mr-wf-create-modal]");
    var open = root.querySelector("[data-mr-wf-create-open]");
    if (!modal || !open) return;
    open.addEventListener("click", function () { modal.showModal(); });
    modal.querySelector("[data-mr-wf-create-close]").addEventListener("click", function () { modal.close(); });
  }

  function boot() {
    var root = document.querySelector("[data-mr-wf-root]");
    if (!root) return;
    initCreateModal(root);
    initOperationClocks(root);
    initStartForm(root);
    initAssistant(root);
    initActive(root);
    initCardActions(root);
    initReadyFilters(root);
    initFinishAlarm(root);
  }

  function initReadyFilters(root) {
    var box = root.querySelector("[data-mr-wf-ready]");
    if (!box) return;
    var rows = Array.prototype.slice.call(box.querySelectorAll("[data-mr-wf-ready-row]"));
    var empty = box.querySelector("[data-mr-wf-ready-empty]");
    var countEl = box.querySelector("[data-mr-wf-ready-count]");
    var clearBtn = box.querySelector("[data-mr-wf-ready-clear]");
    var controls = {};
    box.querySelectorAll("[data-mr-wf-ready-filter]").forEach(function (el) {
      controls[el.getAttribute("data-mr-wf-ready-filter")] = el;
    });
    var STORE_KEY = "mr-wf-ready-filters";
    var PAGE_SIZE = 15;
    var pager = box.querySelector("[data-mr-wf-ready-pager]");
    var pagerInfo = box.querySelector("[data-mr-wf-ready-pager-info]");
    var pagerNums = box.querySelector("[data-mr-wf-ready-pager-nums]");
    var prevBtn = box.querySelector('[data-mr-wf-ready-page="prev"]');
    var nextBtn = box.querySelector('[data-mr-wf-ready-page="next"]');
    var page = 1;

    function pageList(current, total) {
      if (total <= 7) {
        return Array.from({ length: total }, function (_, i) { return i + 1; });
      }
      var out = [1];
      var start = Math.max(2, current - 1);
      var end = Math.min(total - 1, current + 1);
      if (current <= 3) end = 4;
      if (current >= total - 2) start = total - 3;
      if (start > 2) out.push("…");
      for (var i = start; i <= end; i += 1) out.push(i);
      if (end < total - 1) out.push("…");
      out.push(total);
      return out;
    }

    function renderPager(matched) {
      var pages = Math.max(1, Math.ceil(matched.length / PAGE_SIZE));
      if (page > pages) page = pages;
      if (page < 1) page = 1;
      var first = (page - 1) * PAGE_SIZE;
      matched.forEach(function (row, i) {
        row.hidden = i < first || i >= first + PAGE_SIZE;
      });
      if (!pager) return;
      pager.hidden = matched.length === 0;
      if (pagerInfo) {
        pagerInfo.textContent = matched.length
          ? "Showing " + (first + 1) + "–" + Math.min(first + PAGE_SIZE, matched.length) + " of " + matched.length
          : "";
      }
      if (prevBtn) prevBtn.disabled = page <= 1;
      if (nextBtn) nextBtn.disabled = page >= pages;
      if (pagerNums) {
        pagerNums.innerHTML = "";
        pageList(page, pages).forEach(function (n) {
          if (n === "…") {
            var gap = document.createElement("span");
            gap.className = "mr-mc__pager-gap";
            gap.textContent = "…";
            pagerNums.appendChild(gap);
            return;
          }
          var b = document.createElement("button");
          b.type = "button";
          b.className = "mr-mc__pager-btn" + (n === page ? " is-current" : "");
          b.textContent = String(n);
          b.setAttribute("data-mr-wf-ready-page", String(n));
          if (n === page) b.setAttribute("aria-current", "page");
          pagerNums.appendChild(b);
        });
      }
    }

    function values() {
      return {
        q: (controls.q.value || "").trim().toLowerCase(),
        project: controls.project.value,
        by: controls.by.value,
        from: controls.from.value,
        to: controls.to.value,
      };
    }

    function apply() {
      var v = values();
      var words = v.q ? v.q.split(/\s+/) : [];
      var matched = [];
      rows.forEach(function (row) {
        var date = row.getAttribute("data-date") || "";
        var hay = row.getAttribute("data-search") || "";
        var ok = (!v.project || row.getAttribute("data-project") === v.project)
          && (!v.by || row.getAttribute("data-by") === v.by)
          && (!v.from || (date && date >= v.from))
          && (!v.to || (date && date <= v.to))
          && words.every(function (w) { return hay.indexOf(w) >= 0; });
        row.hidden = !ok;
        if (ok) matched.push(row);
      });
      var shown = matched.length;
      renderPager(matched);
      var active = !!(v.q || v.project || v.by || v.from || v.to);
      if (empty) empty.hidden = shown > 0;
      if (countEl) countEl.textContent = active ? shown + " / " + rows.length : String(rows.length);
      if (clearBtn) clearBtn.disabled = !active;
      try {
        window.sessionStorage.setItem(STORE_KEY, JSON.stringify(Object.assign({ page: page }, v)));
      } catch (e) {
        // Storage unavailable — filters still apply for this view.
      }
    }

    try {
      var saved = JSON.parse(window.sessionStorage.getItem(STORE_KEY) || "{}");
      Object.keys(controls).forEach(function (k) {
        if (!saved[k]) return;
        var el = controls[k];
        if (el.tagName === "SELECT" && !el.querySelector('option[value="' + CSS.escape(saved[k]) + '"]')) return;
        el.value = saved[k];
      });
      if (saved.page > 1) page = Math.floor(saved.page);
    } catch (e) {
      // Ignore unreadable saved filters.
    }

    function applyFromFirstPage() {
      page = 1;
      apply();
    }

    Object.keys(controls).forEach(function (k) {
      controls[k].addEventListener(k === "q" ? "input" : "change", applyFromFirstPage);
    });
    if (clearBtn) {
      clearBtn.addEventListener("click", function () {
        Object.keys(controls).forEach(function (k) { controls[k].value = ""; });
        applyFromFirstPage();
        controls.q.focus();
      });
    }
    if (pager) {
      pager.addEventListener("click", function (e) {
        var btn = e.target.closest("[data-mr-wf-ready-page]");
        if (!btn || btn.disabled) return;
        var to = btn.getAttribute("data-mr-wf-ready-page");
        if (to === "prev") page -= 1;
        else if (to === "next") page += 1;
        else page = parseInt(to, 10) || 1;
        apply();
        var wrap = box.querySelector(".mr-mc__ready-wrap");
        if (wrap && wrap.getBoundingClientRect().top < 0) {
          wrap.scrollIntoView({ block: "start", behavior: "smooth" });
        }
      });
    }
    apply();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
