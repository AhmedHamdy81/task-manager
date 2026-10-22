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
      daysSummary.textContent = labels.length ? labels.join(" + ") : "Select shooting days…";
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
          cb.type = "checkbox";
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
      committed = checkedDayIds();
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
          var keep = checkedDayIds();
          if (!d.workflow_id) keep.push(d.id);
          renderDays(keep);
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
        setStartError("Tick at least one shooting day.");
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
      transcode_verify: "[data-mr-wf-transcode-verify]",
      mark_ready: "[data-mr-wf-mark-ready]",
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
        }).then(applyGates);
      });
    });

    function clickAction(sel, url, payloadFn) {
      var el = active.querySelector(sel);
      if (!el) return;
      el.addEventListener("click", function () {
        postJson(url, payloadFn()).then(afterOk);
      });
    }

    var estH = active.querySelector("[data-mr-wf-est-h]");
    var estM = active.querySelector("[data-mr-wf-est-m]");
    function backupEstimateMinutes() {
      if (!estH || !estM) return null;
      return (parseInt(estH.value, 10) || 0) * 60 + (parseInt(estM.value, 10) || 0);
    }
    [estH, estM].forEach(function (sel) {
      if (!sel) return;
      sel.addEventListener("change", function () {
        postJson(backupUrl, {
          action: "save",
          backup_estimated_minutes: backupEstimateMinutes(),
        }).then(applyGates);
      });
    });

    clickAction("[data-mr-wf-backup-start]", backupUrl, function () {
      return {
        action: "start",
        backup_estimated_minutes: backupEstimateMinutes(),
        backup_destination_id: checkedCardId("data-mr-wf-backup-dest"),
      };
    });
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

    var preset = active.querySelector("[data-mr-wf-preset]");
    function saveTranscodeTarget() {
      postJson(transcodeUrl, {
        action: "save",
        proxy_destination_id: checkedCardId("data-mr-wf-proxy-dest"),
        proxy_preset: (preset && preset.value) || "",
      }).then(applyGates);
    }
    active.querySelectorAll("[data-mr-wf-proxy-dest]").forEach(function (card) {
      card.addEventListener("change", saveTranscodeTarget);
    });
    if (preset) preset.addEventListener("change", saveTranscodeTarget);

    clickAction("[data-mr-wf-transcode-start]", transcodeUrl, function () {
      return {
        action: "start",
        proxy_destination_id: checkedCardId("data-mr-wf-proxy-dest"),
        proxy_preset: (active.querySelector("[data-mr-wf-preset]") || {}).value || "",
        pre_checks: collectedChecks("[data-mr-wf-pre-check]"),
      };
    });
    clickAction("[data-mr-wf-transcode-finish]", transcodeUrl, function () {
      return { action: "finish" };
    });
    clickAction("[data-mr-wf-transcode-verify]", transcodeUrl, function () {
      return {
        action: "verify",
        post_checks: collectedChecks("[data-mr-wf-post-check]"),
      };
    });
    clickAction("[data-mr-wf-mark-ready]", completeUrl, function () {
      return {
        action: "mark_ready",
        checks: collectedChecks("[data-mr-wf-complete-check]"),
      };
    });

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

  var ASSISTANT_KEY = "mrWfAssistantCollapsed";

  function initAssistant(root) {
    var box = root.querySelector("[data-mr-wf-assistant]");
    if (!box) return;
    try {
      if (window.localStorage.getItem(ASSISTANT_KEY) === "1") box.open = false;
    } catch (e) {
      // Storage unavailable — keep the default open state.
    }
    box.addEventListener("toggle", function () {
      try {
        window.localStorage.setItem(ASSISTANT_KEY, box.open ? "0" : "1");
      } catch (e) {
        // Storage unavailable — collapse still works for this page view.
      }
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

  function boot() {
    var root = document.querySelector("[data-mr-wf-root]");
    if (!root) return;
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
