(function () {
  "use strict";

  function postJson(url, body) {
    return fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        "X-Requested-With": "fetch",
      },
      body: JSON.stringify(body),
    }).then(function (r) {
      return r.json().then(function (payload) {
        if (!r.ok) {
          var err = new Error((payload && payload.error) || "request_failed");
          err.payload = payload;
          throw err;
        }
        return payload;
      });
    });
  }

  function updateRowBadge(row, payload) {
    var badge = row.querySelector(".admin-task-log-status");
    if (badge && payload.status_label) {
      badge.textContent = payload.status_label;
      badge.className = "admin-task-log-status admin-task-log-status--" + String(payload.status || "");
    }
    var completedCell = row.cells && row.cells[9];
    if (completedCell && payload.completed_at !== undefined) {
      completedCell.textContent = payload.completed_at || "—";
    }
    var latestCell = row.cells && row.cells[10];
    if (latestCell && payload.latest_update !== undefined) {
      latestCell.textContent = payload.latest_update || "—";
    }
    var select = row.querySelector(".admin-task-log-status-select");
    if (select && payload.status) {
      select.value = payload.status;
      select.setAttribute("data-last-status", payload.status);
    }
  }

  function showFailureNote(row) {
    var title = row.getAttribute("data-failure-note-title") || "Failure note";
    var body = row.getAttribute("data-failure-note-body") || "";
    var dlg = document.getElementById("admin-task-log-failure-note-modal");
    var titleEl = document.getElementById("admin-task-log-failure-note-title");
    var bodyEl = document.getElementById("admin-task-log-failure-note-body");
    if (!dlg || !bodyEl) {
      window.alert(title + "\n\n" + body);
      return;
    }
    if (titleEl) titleEl.textContent = title;
    bodyEl.textContent = body;
    if (typeof dlg.showModal === "function") dlg.showModal();
  }

  document.querySelectorAll(".admin-task-log-status-form").forEach(function (form) {
    var url = form.getAttribute("data-status-url");
    var conformStatusUrl = form.getAttribute("data-conform-status-url");
    var taskId = form.getAttribute("data-task-id");
    var isConform = form.getAttribute("data-is-conform-task") === "1";
    var select = form.querySelector(".admin-task-log-status-select");
    var btn = form.querySelector(".admin-task-log-status-save");
    if (!select || !btn) return;

    if (select.value) {
      select.setAttribute("data-last-status", select.value);
    }

    btn.addEventListener("click", function () {
      var row = form.closest(".admin-task-log-row");
      var status = select.value;
      var prevStatus = select.getAttribute("data-last-status") || status;

      if (isConform && status === "done") {
        if (window.__conformFinish && typeof window.__conformFinish.openFinishModal === "function") {
          window.__conformFinish.openFinishModal(taskId, {
            onSaved: function () {
              window.location.reload();
            },
          });
        } else {
          window.alert("Finish form is not available. Reload the page and try again.");
        }
        select.value = prevStatus;
        return;
      }

      btn.disabled = true;
      select.disabled = true;
      btn.textContent = "Saving…";

      var request;
      if (isConform && conformStatusUrl) {
        request = postJson(conformStatusUrl, { status: status, _prev_status: prevStatus });
      } else if (url) {
        request = postJson(url, { status: status });
      } else {
        btn.disabled = false;
        select.disabled = false;
        btn.textContent = "Save";
        return;
      }

      request
        .then(function (payload) {
          var rowPayload = payload;
          if (isConform) {
            rowPayload = {
              status: payload.status,
              status_label:
                payload.status === "done"
                  ? "Done"
                  : payload.status === "in_progress"
                    ? "In progress"
                    : payload.status === "open"
                      ? "Open"
                      : payload.status,
              completed_at: payload.status === "done" ? "now" : "",
            };
          }
          if (row) updateRowBadge(row, rowPayload);
          select.setAttribute("data-last-status", status);
          btn.textContent = "Saved";
          setTimeout(function () {
            btn.textContent = "Save";
          }, 1200);
        })
        .catch(function (err) {
          select.value = prevStatus;
          btn.textContent = "Error";
          var msg =
            (err && err.payload && err.payload.error) ||
            "Could not update task status. Please try again.";
          window.alert(msg);
          setTimeout(function () {
            btn.textContent = "Save";
          }, 1500);
        })
        .finally(function () {
          btn.disabled = false;
          select.disabled = false;
        });
    });
  });

  document.querySelectorAll("[data-admin-failure-note]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var row = btn.closest(".admin-task-log-row");
      if (row) showFailureNote(row);
    });
  });

  document.querySelectorAll("[data-admin-failure-note-close]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var dlg = btn.closest("dialog");
      if (dlg && typeof dlg.close === "function") dlg.close();
    });
  });
})();
