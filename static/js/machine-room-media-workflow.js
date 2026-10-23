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

    function setStartError(msg) {
      if (!startError) return;
      startError.textContent = msg || "";
      startError.hidden = !msg;
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
          open.className = "mr-mc__day-open";
          open.href = workflowUrl(d.workflow_id);
          open.textContent = "Open";
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
          day_name: newDayField("data-mr-wf-new-day-name").value,
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
      if (!projectSel.value) {
        setStartError("Select a project first.");
        return;
      }
      if (!ids.length) {
        setStartError("Select a shooting day.");
        return;
      }
      postJson(root.getAttribute("data-create-url"), {
        project_id: parseInt(projectSel.value, 10),
        shooting_day_ids: ids,
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
    wireSaveChecks("[data-mr-wf-backup-check]", backupUrl);
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
    var confirmChecks = confirmModal ? confirmModal.querySelector("[data-mr-wf-confirm-checks]") : null;

    function confirmCheckState() {
      if (!confirmChecks) return { keys: [], all: false };
      var boxes = confirmChecks.querySelectorAll("[data-mr-wf-confirm-check]");
      var keys = Array.prototype.filter.call(boxes, function (b) { return b.checked; })
        .map(function (b) { return b.value; });
      return { keys: keys, all: boxes.length > 0 && keys.length === boxes.length };
    }

    function syncConfirmButton() {
      if (!confirmModal || !pendingFinish) return;
      var button = confirmModal.querySelector('[value="confirm"]');
      var note = confirmModal.querySelector("[data-mr-wf-confirm-note]");
      if (pendingFinish.kind !== "transcode") {
        button.textContent = "Record finished";
        if (note) note.textContent = "The finish time is recorded now. Verification is a separate step.";
        return;
      }
      var state = confirmCheckState();
      button.textContent = state.all ? "Record finished & verify proxies" : "Record finished";
      if (note) {
        note.textContent = state.all
          ? "All checks ticked — proxies are marked verified and the workflow moves to Complete."
          : "Tick every check to verify the proxies now, or record the finish and verify later.";
      }
    }

    function confirmFinish(url, payload, kind) {
      if (!confirmModal) return;
      pendingFinish = {url: url, payload: payload, kind: kind};
      confirmModal.querySelector("[data-mr-wf-confirm-title]").textContent = kind === "copy" ? "Record copy finished" : "Record transcoding finished";
      confirmModal.querySelector("[data-mr-wf-confirm-description]").textContent = kind === "copy"
        ? "Confirm the copy tool has finished. Next: verify the copied original media before creating proxies."
        : "Confirm the conversion tool has finished, then check the generated proxies.";
      if (confirmChecks) confirmChecks.hidden = kind !== "transcode";
      confirmModal.querySelector("[data-mr-wf-confirm-error]").hidden = true;
      syncConfirmButton();
      confirmModal.showModal();
    }
    if (confirmChecks) confirmChecks.addEventListener("change", syncConfirmButton);
    if (confirmModal) {
      confirmModal.querySelector("form").addEventListener("submit", function (event) {
        event.preventDefault();
        if (event.submitter && event.submitter.value === "cancel") {
          confirmModal.close(); pendingFinish = null; return;
        }
        if (!pendingFinish) return;
        var button = confirmModal.querySelector('[value="confirm"]');
        if (button.disabled) return;
        button.disabled = true;
        var finish = pendingFinish;
        var checks = finish.kind === "transcode" ? confirmCheckState() : null;
        var payload = Object.assign({}, finish.payload);
        if (checks) payload.post_checks = checks.keys;
        postJson(finish.url, payload).then(function (res) {
          if (res.ok && checks && checks.all) {
            return postJson(finish.url, { action: "verify", post_checks: checks.keys });
          }
          return res;
        }).then(function (res) {
          if (res.ok) { confirmModal.close(); afterOk(res); }
          else {
            var error = confirmModal.querySelector("[data-mr-wf-confirm-error]");
            error.textContent = (res.data && res.data.error) || "Could not record completion.";
            error.hidden = false;
          }
        }).catch(function () {
          var error = confirmModal.querySelector("[data-mr-wf-confirm-error]");
          error.textContent = "Connection lost. Close and reopen the workflow to check whether completion was saved.";
          error.hidden = false;
        }).finally(function () { button.disabled = false; });
      });
      confirmModal.addEventListener("close", function () { pendingFinish = null; });
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
      return {
        action: "verify",
        checks: collectedChecks("[data-mr-wf-backup-check]"),
        verification_method: "operator_confirmed",
      };
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
        if (tPath && !tPath.dataset.touched && remembered) {
          tPath.value = remembered;
          setTHint("Restored last selected folder on this volume");
        }
        if (typeof tModal.showModal === "function") tModal.showModal();
        if (tEst && window.Dts) window.Dts.setTotalMinutes(tEst, tSavedEst);
      });
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
        postJson(url, payloadFn()).then(function (res) {
          if (!res.ok) {
            errEl.textContent = (res.data && res.data.error) || failMsg;
            errEl.hidden = false;
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
      return { action: "verify", post_checks: collectedChecks("[data-mr-wf-post-check]") };
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
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
