(function () {
  "use strict";

  var JSON_ACCEPT = { Accept: "application/json", "Content-Type": "application/json" };

  function showError(el, msg) {
    if (!el) return;
    if (msg) {
      el.textContent = msg;
      el.hidden = false;
    } else {
      el.textContent = "";
      el.hidden = true;
    }
  }

  function todayISO() {
    var n = new Date();
    var y = n.getFullYear();
    var m = String(n.getMonth() + 1).padStart(2, "0");
    var d = String(n.getDate()).padStart(2, "0");
    return y + "-" + m + "-" + d;
  }

  function wireFullDay(checkbox, endInput, endWrap) {
    if (!checkbox) return;
    function sync() {
      var on = checkbox.checked;
      if (endInput) {
        endInput.disabled = on;
        if (on) endInput.value = "23:59";
      }
      if (endWrap) endWrap.classList.toggle("is-muted", on);
    }
    checkbox.addEventListener("change", sync);
    sync();
  }

  function setMinDate(input) {
    if (!input) return;
    input.min = todayISO();
    if (input.value && input.value < input.min) input.value = input.min;
  }

  /** @param {HTMLElement} card */
  function renderDashboardBooking(card, payload) {
    if (!card) return;
    var filled = document.getElementById("dashboard-booking-filled");
    var empty = document.getElementById("dashboard-booking-empty");
    if (!filled || !empty) return;
    var b = payload && payload.booking;
    if (!b) {
      filled.hidden = true;
      empty.hidden = false;
      return;
    }
    filled.hidden = false;
    empty.hidden = true;
    var suite = document.getElementById("db-booking-suite");
    var time = document.getElementById("db-booking-time");
    var proj = document.getElementById("db-booking-project");
    var forEl = document.getElementById("db-booking-for");
    if (suite) suite.textContent = b.suite_name || "Room";
    if (time) {
      time.textContent =
        (b.start_time || "").slice(0, 5) +
        "–" +
        (b.end_time || "").slice(0, 5) +
        (b.is_full_day ? " · Full day" : "");
    }
    if (proj) proj.textContent = b.project_name || "";
    if (forEl) forEl.textContent = b.booked_for_name ? "For " + b.booked_for_name : "";
  }

  function createBookingRowShell() {
    var li = document.createElement("li");
    li.className = "booking-row-linear";
    var timeEl = document.createElement("div");
    timeEl.className = "booking-row-linear-time";
    timeEl.setAttribute("data-f", "time");
    var main = document.createElement("div");
    main.className = "booking-row-linear-main";
    var title = document.createElement("div");
    title.className = "booking-row-linear-title";
    title.setAttribute("data-f", "title");
    var sub = document.createElement("div");
    sub.className = "booking-row-linear-sub";
    sub.setAttribute("data-f", "sub");
    var meta = document.createElement("div");
    meta.className = "booking-row-linear-meta";
    meta.setAttribute("data-f", "meta");
    main.appendChild(title);
    main.appendChild(sub);
    main.appendChild(meta);
    var actions = document.createElement("div");
    actions.className = "booking-row-linear-actions";
    var status = document.createElement("span");
    status.className = "booking-pill booking-pill--ok";
    status.setAttribute("data-f", "status");
    status.textContent = "Booked";
    var more = document.createElement("div");
    more.className = "booking-booking-actions";
    var editBtn = document.createElement("button");
    editBtn.type = "button";
    editBtn.className = "btn btn--small btn--ghost";
    editBtn.setAttribute("data-book-act", "edit");
    editBtn.textContent = "⋯";
    editBtn.setAttribute("aria-label", "Edit");
    var cancelBtn = document.createElement("button");
    cancelBtn.type = "button";
    cancelBtn.className = "btn btn--small btn--danger";
    cancelBtn.setAttribute("data-book-act", "cancel");
    cancelBtn.textContent = "Cancel";
    more.appendChild(editBtn);
    more.appendChild(cancelBtn);
    actions.appendChild(status);
    actions.appendChild(more);
    li.appendChild(timeEl);
    li.appendChild(main);
    li.appendChild(actions);
    return li;
  }

  function fillBookingRow(li, b) {
    li.setAttribute("data-booking-id", String(b.id));
    li.setAttribute("data-booking-date", b.booking_date || "");
    var timeEl = li.querySelector('[data-f="time"]');
    if (timeEl) {
      timeEl.textContent =
        (b.start_time || "").slice(0, 5) + "–" + (b.end_time || "").slice(0, 5);
    }
    var title = li.querySelector('[data-f="title"]');
    if (title) {
      title.textContent = (b.suite_name || "Room") + "  ·  " + (b.project_name || "—");
    }
    var sub = li.querySelector('[data-f="sub"]');
    if (sub) {
      sub.textContent =
        (b.booked_by_name || "—") + "  →  " + (b.booked_for_name || "—");
    }
    var meta = li.querySelector('[data-f="meta"]');
    if (meta) {
      var nt = (b.notes || "").trim();
      meta.textContent = b.booking_date + (nt ? " · " + (nt.length > 60 ? nt.slice(0, 57) + "…" : nt) : "");
      meta.title = nt;
    }
    var st = li.querySelector('[data-f="status"]');
    if (st) {
      st.textContent = b.is_active ? "Booked" : "Cancelled";
      st.className = b.is_active ? "booking-pill booking-pill--ok" : "booking-pill booking-pill--muted";
    }
    li._bookingData = b;
  }

  /**
   * Incremental sync: append/update/remove rows only (no list innerHTML wipe).
   * @param {HTMLUListElement} ul
   * @param {object[]} rows
   * @param {{ onEdit?: function, onCancel?: function }} handlers
   */
  function renderBookings(ul, rows, handlers) {
    if (!ul) return;
    handlers = handlers || {};
    ul._rowMap = ul._rowMap || {};
    if (!ul._delegateAttached) {
      ul._delegateAttached = true;
      ul.addEventListener("click", function (e) {
        var act = e.target.closest("[data-book-act]");
        if (!act || !ul.contains(act)) return;
        var row = act.closest("[data-booking-id]");
        if (!row || !row._bookingData) return;
        var b = row._bookingData;
        if (act.getAttribute("data-book-act") === "edit" && handlers.onEdit) handlers.onEdit(b);
        if (act.getAttribute("data-book-act") === "cancel" && handlers.onCancel) handlers.onCancel(b);
      });
    }
    rows = rows || [];
    var next = {};
    rows.forEach(function (b) {
      next[String(b.id)] = true;
    });
    Object.keys(ul._rowMap).forEach(function (k) {
      if (!next[k]) {
        var li = ul._rowMap[k];
        if (li && li.parentNode === ul) ul.removeChild(li);
        delete ul._rowMap[k];
      }
    });
    rows.forEach(function (b) {
      var key = String(b.id);
      var li = ul._rowMap[key];
      if (!li) {
        li = createBookingRowShell();
        ul.appendChild(li);
        ul._rowMap[key] = li;
      }
      fillBookingRow(li, b);
    });
  }

  function createSuiteRowShell(admin) {
    var li = document.createElement("li");
    li.className = "booking-suite-row";
    var nameSpan = document.createElement("span");
    nameSpan.className = "booking-suite-row-name";
    nameSpan.setAttribute("data-f", "name");
    var statusSpan = document.createElement("span");
    statusSpan.setAttribute("data-f", "status");
    li.appendChild(nameSpan);
    li.appendChild(statusSpan);
    if (admin) {
      var actions = document.createElement("span");
      actions.className = "booking-suite-row-actions";
      var editBtn = document.createElement("button");
      editBtn.type = "button";
      editBtn.className = "btn btn--small btn--ghost";
      editBtn.setAttribute("data-suite-act", "edit");
      editBtn.textContent = "Edit";
      var delBtn = document.createElement("button");
      delBtn.type = "button";
      delBtn.className = "btn btn--small btn--danger";
      delBtn.setAttribute("data-suite-act", "delete");
      delBtn.textContent = "Delete";
      actions.appendChild(editBtn);
      actions.appendChild(delBtn);
      li.appendChild(actions);
    }
    return li;
  }

  function fillSuiteRow(li, s) {
    li.setAttribute("data-suite-id", String(s.id));
    var nameEl = li.querySelector('[data-f="name"]');
    var stEl = li.querySelector('[data-f="status"]');
    if (nameEl) nameEl.textContent = s.name || "";
    if (stEl) {
      stEl.textContent = s.is_active ? "Active" : "Inactive";
      stEl.className = s.is_active ? "booking-pill booking-pill--ok" : "booking-pill booking-pill--muted";
    }
    var delBtn = li.querySelector('[data-suite-act="delete"]');
    if (delBtn) delBtn.disabled = !s.is_active;
    li._suiteData = s;
  }

  /**
   * @param {HTMLUListElement} listEl
   * @param {Array<{id:number,name:string,is_active:boolean}>} suites
   * @param {{ onEdit?: function, onDelete?: function, admin?: boolean }} opts
   */
  function renderSuites(listEl, suites, opts) {
    if (!listEl) return;
    opts = opts || {};
    listEl._suiteMap = listEl._suiteMap || {};
    if (opts.admin && !listEl._suiteDelegateAttached) {
      listEl._suiteDelegateAttached = true;
      listEl.addEventListener("click", function (e) {
        var act = e.target.closest("[data-suite-act]");
        if (!act || !listEl.contains(act)) return;
        var row = act.closest("[data-suite-id]");
        if (!row || !row._suiteData) return;
        var s = row._suiteData;
        if (act.getAttribute("data-suite-act") === "edit" && opts.onEdit) opts.onEdit(s);
        if (act.getAttribute("data-suite-act") === "delete" && opts.onDelete) opts.onDelete(s);
      });
    }
    suites = suites || [];
    var next = {};
    suites.forEach(function (s) {
      next[String(s.id)] = true;
    });
    Object.keys(listEl._suiteMap).forEach(function (k) {
      if (!next[k]) {
        var li = listEl._suiteMap[k];
        if (li && li.parentNode === listEl) listEl.removeChild(li);
        delete listEl._suiteMap[k];
      }
    });
    suites.forEach(function (s) {
      var key = String(s.id);
      var li = listEl._suiteMap[key];
      if (!li) {
        li = createSuiteRowShell(!!opts.admin);
        listEl.appendChild(li);
        listEl._suiteMap[key] = li;
      }
      fillSuiteRow(li, s);
    });
  }

  function fillSelect(sel, items, getValue, getLabel, placeholder) {
    if (!sel) return;
    var keep = document.createDocumentFragment();
    if (placeholder) {
      var ph = document.createElement("option");
      ph.value = "";
      ph.textContent = placeholder;
      keep.appendChild(ph);
    }
    (items || []).forEach(function (it) {
      var opt = document.createElement("option");
      opt.value = String(getValue(it));
      opt.textContent = getLabel(it);
      keep.appendChild(opt);
    });
    sel.textContent = "";
    sel.appendChild(keep);
  }

  function initDashboardCard() {
    var card = document.getElementById("dashboard-booking-card");
    if (!card) return;
    var url = card.getAttribute("data-today-url");
    if (!url) return;
    fetch(url, { headers: { Accept: "application/json" }, credentials: "same-origin" })
      .then(function (r) {
        return r.json();
      })
      .then(function (j) {
        renderDashboardBooking(card, j);
      })
      .catch(function () {
        /* keep server-rendered content */
      });
  }

  function initBookingPage(root) {
    var listUrl = root.getAttribute("data-list-url") || "";
    var suitesUrl = root.getAttribute("data-suites-url") || "";
    var projectsUrl = root.getAttribute("data-projects-url") || "";
    var usersUrl = root.getAttribute("data-users-url") || "";
    var todayUrl = root.getAttribute("data-today-url") || "";
    var form = document.getElementById("booking-form");
    var suiteSel = document.getElementById("booking-suite");
    var projectSel = document.getElementById("booking-project");
    var dateIn = document.getElementById("booking-date");
    var startIn = document.getElementById("booking-start");
    var endIn = document.getElementById("booking-end");
    var fullDay = document.getElementById("booking-full-day");
    var bookedForSel = document.getElementById("booking-booked-for");
    var notesTa = document.getElementById("booking-notes");
    var errEl = document.getElementById("booking-form-error");
    var okEl = document.getElementById("booking-form-success");
    var submitBtn = document.getElementById("booking-submit");
    var endWrap = document.getElementById("booking-end-wrap");

    var ulMine = document.getElementById("booking-list-mine");
    var ulAsg = document.getElementById("booking-list-assigned");
    var loadMine = document.getElementById("booking-list-mine-loading");
    var loadAsg = document.getElementById("booking-list-assigned-loading");
    var emptyMine = document.getElementById("booking-list-mine-empty");
    var emptyAsg = document.getElementById("booking-list-assigned-empty");
    var listsErr = document.getElementById("booking-lists-error");

    var editHost = document.getElementById("booking-edit-host");
    var editParking = document.getElementById("booking-edit-parking");
    var bookingPageSection = document.getElementById("booking-page-section");
    var editForm = document.getElementById("booking-edit-form");
    var editId = document.getElementById("booking-edit-id");
    var editSuite = document.getElementById("booking-edit-suite");
    var editProject = document.getElementById("booking-edit-project");
    var editBookedFor = document.getElementById("booking-edit-booked-for");
    var editDate = document.getElementById("booking-edit-date");
    var editStart = document.getElementById("booking-edit-start");
    var editEnd = document.getElementById("booking-edit-end");
    var editFull = document.getElementById("booking-edit-full-day");
    var editNotes = document.getElementById("booking-edit-notes");
    var editErr = document.getElementById("booking-edit-error");
    var editEndWrap = document.getElementById("booking-edit-end-wrap");

    var cacheSuites = [];
    var cacheProjects = [];
    var cacheUsers = [];
    var mergedForTimeline = [];

    var H_START = 8;
    var H_END = 20;
    var ROW_PX = 32;

    function parseTimeToMin(s) {
      var p = String(s || "").split(":");
      var h = parseInt(p[0], 10);
      var m = parseInt(p[1] || "0", 10);
      if (isNaN(h)) return 0;
      return h * 60 + (isNaN(m) ? 0 : m);
    }

    function renderTimeline() {
      var inner = document.getElementById("booking-timeline-inner");
      var wrap = document.getElementById("booking-timeline-wrap");
      if (!inner || !wrap || !bookingPageSection || !bookingPageSection.classList.contains("is-timeline")) {
        return;
      }
      var dateStr = dateIn ? dateIn.value : todayISO();
      var suites = cacheSuites.filter(function (s) {
        return s.is_active;
      });
      if (!suites.length) {
        inner.textContent = "";
        var empty = document.createElement("p");
        empty.className = "empty";
        empty.style.padding = "1rem";
        empty.textContent = "No rooms to display.";
        inner.appendChild(empty);
        return;
      }
      var lh = listHandlers();
      var totalMin = (H_END - H_START) * 60;
      inner.textContent = "";
      var flex = document.createElement("div");
      flex.className = "booking-timeline-flex";
      flex.style.display = "flex";
      flex.style.gap = "0";
      flex.style.minHeight = (H_END - H_START) * ROW_PX + 24 + "px";

      var hoursCol = document.createElement("div");
      hoursCol.style.width = "48px";
      hoursCol.style.flexShrink = "0";
      hoursCol.style.paddingTop = "28px";
      for (var hh = H_START; hh < H_END; hh++) {
        var hl = document.createElement("div");
        hl.style.height = ROW_PX + "px";
        hl.style.fontSize = "0.65rem";
        hl.style.color = "var(--text-secondary, #9aa4b2)";
        hl.style.textAlign = "right";
        hl.style.paddingRight = "6px";
        hl.textContent = (hh < 10 ? "0" : "") + hh + ":00";
        hoursCol.appendChild(hl);
      }
      flex.appendChild(hoursCol);

      var roomsRow = document.createElement("div");
      roomsRow.style.display = "flex";
      roomsRow.style.flex = "1";
      roomsRow.style.gap = "1px";
      roomsRow.style.background = "var(--border, rgba(255,255,255,0.06))";

      suites.forEach(function (suite) {
        var col = document.createElement("div");
        col.style.flex = "1";
        col.style.minWidth = "100px";
        col.style.position = "relative";
        col.style.background = "var(--surface, #151821)";
        var head = document.createElement("div");
        head.style.fontSize = "0.65rem";
        head.style.fontWeight = "600";
        head.style.textTransform = "uppercase";
        head.style.letterSpacing = "0.04em";
        head.style.color = "var(--text-secondary)";
        head.style.padding = "6px 8px";
        head.style.borderBottom = "1px solid var(--border, rgba(255,255,255,0.06))";
        head.textContent = suite.name;
        col.appendChild(head);
        var track = document.createElement("div");
        track.style.position = "relative";
        track.style.height = (H_END - H_START) * ROW_PX + "px";
        track.style.background = "rgba(255,255,255,0.02)";
        for (var h2 = H_START; h2 < H_END; h2++) {
          var line = document.createElement("div");
          line.style.height = ROW_PX - 1 + "px";
          line.style.borderBottom = "1px solid var(--border, rgba(255,255,255,0.06))";
          track.appendChild(line);
        }
        (mergedForTimeline || []).forEach(function (bk) {
          if (bk.booking_date !== dateStr || bk.edit_suite_id !== suite.id) return;
          var sm = parseTimeToMin(bk.start_time);
          var em = parseTimeToMin(bk.end_time);
          var startRel = sm - H_START * 60;
          var dur = Math.max(15, em - sm);
          if (startRel < 0 || startRel >= totalMin) return;
          var topPct = (startRel / totalMin) * 100;
          var hPct = (dur / totalMin) * 100;
          var blk = document.createElement("button");
          blk.type = "button";
          blk.className = "booking-timeline-block";
          blk.style.top = topPct + "%";
          blk.style.height = hPct + "%";
          blk.style.position = "absolute";
          blk.style.left = "2px";
          blk.style.right = "2px";
          blk.textContent = (bk.start_time || "").slice(0, 5) + " " + (bk.project_name || "").slice(0, 12);
          blk._bookingData = bk;
          blk.addEventListener("click", function (e) {
            e.preventDefault();
            if (blk._bookingData && lh.onEdit) lh.onEdit(blk._bookingData);
          });
          track.appendChild(blk);
        });
        col.appendChild(track);
        roomsRow.appendChild(col);
      });
      flex.appendChild(roomsRow);
      inner.appendChild(flex);
    }

    function setViewMode(isTimeline) {
      if (!bookingPageSection) return;
      bookingPageSection.classList.toggle("is-timeline", isTimeline);
      bookingPageSection.classList.toggle("booking-list-mode", !isTimeline);
      var wrap = document.getElementById("booking-timeline-wrap");
      var btnL = document.getElementById("booking-view-list");
      var btnT = document.getElementById("booking-view-timeline");
      if (btnL && btnT) {
        btnL.classList.toggle("is-active", !isTimeline);
        btnT.classList.toggle("is-active", isTimeline);
        btnL.setAttribute("aria-pressed", !isTimeline ? "true" : "false");
        btnT.setAttribute("aria-pressed", isTimeline ? "true" : "false");
      }
      if (wrap) wrap.hidden = !isTimeline;
      if (isTimeline) renderTimeline();
    }

    function openEditDialog(b) {
      showError(editErr, "");
      function fillEditSelects(usersForBookedFor) {
        usersForBookedFor = usersForBookedFor || cacheUsers;
        fillSelect(
          editSuite,
          cacheSuites.filter(function (s) {
            return s.is_active;
          }),
          function (x) {
            return x.id;
          },
          function (x) {
            return x.name;
          },
          null
        );
        fillSelect(
          editProject,
          cacheProjects,
          function (x) {
            return x.id;
          },
          function (x) {
            return x.name;
          },
          null
        );
        fillSelect(
          editBookedFor,
          usersForBookedFor,
          function (x) {
            return x.id;
          },
          function (x) {
            return x.name;
          },
          null
        );
        editId.value = String(b.id);
        editSuite.value = String(b.edit_suite_id);
        editProject.value = String(b.project_id);
        editBookedFor.value = String(b.booked_for_id);
        editDate.value = b.booking_date;
        editStart.value = (b.start_time || "").slice(0, 5);
        editFull.checked = !!b.is_full_day;
        if (!b.is_full_day) editEnd.value = (b.end_time || "").slice(0, 5);
        if (editNotes) editNotes.value = (b.notes || "").trim();
        setMinDate(editDate);
        if (editEnd) {
          editEnd.disabled = !!editFull.checked;
          editEnd.value = editFull.checked ? "23:59" : (b.end_time || "").slice(0, 5);
        }
        if (editEndWrap) editEndWrap.classList.toggle("is-muted", !!editFull.checked);
        if (window.tmShell && editHost && editParking) {
          window.tmShell.openInspector({
            title: "Edit booking",
            el: editHost,
            parking: editParking,
          });
        }
      }
      function loadUsersThenFill() {
        var sep = usersUrl.indexOf("?") >= 0 ? "&" : "?";
        var uUrl =
          usersUrl + sep + "include_user_id=" + encodeURIComponent(String(b.booked_for_id));
        fetch(uUrl, { headers: { Accept: "application/json" }, credentials: "same-origin" })
          .then(function (r) {
            return r.json();
          })
          .then(function (ju) {
            fillEditSelects((ju && ju.users) || cacheUsers);
          })
          .catch(function () {
            fillEditSelects(cacheUsers);
          });
      }
      if (cacheSuites.length && cacheProjects.length) {
        loadUsersThenFill();
      } else {
        loadMeta(loadUsersThenFill);
      }
    }

    function listHandlers() {
      return {
        onEdit: function (b) {
          openEditDialog(b);
        },
        onCancel: function (b) {
          if (!window.confirm("Cancel this booking?")) return;
          fetch(listUrl.replace(/\/?$/, "") + "/" + b.id, {
            method: "DELETE",
            headers: { Accept: "application/json" },
            credentials: "same-origin",
          })
            .then(function (r) {
              return r.json().then(function (j) {
                return { ok: r.ok, j: j };
              });
            })
            .then(function (x) {
              if (!x.ok) {
                showError(listsErr, (x.j && x.j.message) || "Could not cancel.");
                return;
              }
              refreshLists();
              bumpDashboardIfToday(b);
            })
            .catch(function () {
              showError(listsErr, "Network error.");
            });
        },
      };
    }

    function refreshLists() {
      showError(listsErr, "");
      fetch(listUrl + (listUrl.indexOf("?") >= 0 ? "&" : "?") + "json=1", {
        headers: { Accept: "application/json" },
        credentials: "same-origin",
      })
        .then(function (r) {
          return r.json();
        })
        .then(function (j) {
          var mine = (j && j.bookings_mine) || [];
          var asg = (j && j.bookings_assigned) || [];
          if (loadMine) loadMine.hidden = true;
          if (loadAsg) loadAsg.hidden = true;
          if (emptyMine) emptyMine.hidden = mine.length > 0;
          if (emptyAsg) emptyAsg.hidden = asg.length > 0;
          if (ulMine) {
            ulMine.hidden = mine.length === 0;
            renderBookings(ulMine, mine, listHandlers());
          }
          if (ulAsg) {
            ulAsg.hidden = asg.length === 0;
            renderBookings(ulAsg, asg, listHandlers());
          }
          mergedForTimeline = mine.concat(asg);
          if (bookingPageSection && bookingPageSection.classList.contains("is-timeline")) {
            renderTimeline();
          }
        })
        .catch(function () {
          showError(listsErr, "Could not load bookings.");
          if (loadMine) loadMine.hidden = true;
          if (loadAsg) loadAsg.hidden = true;
        });
    }

    function bumpDashboardIfToday(b) {
      if (!todayUrl || !b || !b.booking_date) return;
      if (b.booking_date !== todayISO()) return;
      fetch(todayUrl, { headers: { Accept: "application/json" }, credentials: "same-origin" })
        .then(function (r) {
          return r.json();
        })
        .then(function (j) {
          var card = document.getElementById("dashboard-booking-card");
          if (card) renderDashboardBooking(card, j);
        })
        .catch(function () {});
    }

    function loadMeta(done) {
      Promise.all([
        fetch(suitesUrl, { headers: { Accept: "application/json" }, credentials: "same-origin" }).then(function (r) {
          return r.json();
        }),
        fetch(projectsUrl, { headers: { Accept: "application/json" }, credentials: "same-origin" }).then(function (r) {
          return r.json();
        }),
        fetch(usersUrl, { headers: { Accept: "application/json" }, credentials: "same-origin" }).then(function (r) {
          return r.json();
        }),
      ])
        .then(function (parts) {
          cacheSuites = (parts[0] && parts[0].suites) || [];
          cacheProjects = (parts[1] && parts[1].projects) || [];
          cacheUsers = (parts[2] && parts[2].users) || [];
          if (done) done();
        })
        .catch(function () {
          if (done) done();
        });
    }

    if (form && suiteSel && projectSel && dateIn && bookedForSel) {
      setMinDate(dateIn);
      dateIn.addEventListener("focus", function () {
        setMinDate(dateIn);
      });
      dateIn.value = todayISO();
      if (startIn && !startIn.value) startIn.value = "09:00";
      wireFullDay(fullDay, endIn, endWrap);

      loadMeta(function () {
        var activeSuites = cacheSuites.filter(function (s) {
          return s.is_active;
        });
        fillSelect(
          suiteSel,
          activeSuites,
          function (x) {
            return x.id;
          },
          function (x) {
            return x.name;
          },
          activeSuites.length ? null : "No rooms"
        );
        fillSelect(
          projectSel,
          cacheProjects,
          function (x) {
            return x.id;
          },
          function (x) {
            return x.name;
          },
          cacheProjects.length ? null : "No projects"
        );
        fillSelect(
          bookedForSel,
          cacheUsers,
          function (x) {
            return x.id;
          },
          function (x) {
            return x.name;
          },
          cacheUsers.length ? null : "No users"
        );
        if (!activeSuites.length || !cacheProjects.length || !cacheUsers.length) {
          if (submitBtn) submitBtn.disabled = true;
        }
      });

      form.addEventListener("submit", function (e) {
        e.preventDefault();
        showError(errEl, "");
        if (okEl) {
          okEl.textContent = "";
          okEl.hidden = true;
        }
        var sid = parseInt(suiteSel.value, 10);
        var pid = parseInt(projectSel.value, 10);
        var fid = parseInt(bookedForSel.value, 10);
        if (!sid) {
          showError(errEl, "Select a room.");
          return;
        }
        if (!pid) {
          showError(errEl, "Select a project.");
          return;
        }
        if (!fid) {
          showError(errEl, "Select who the booking is for.");
          return;
        }
        setMinDate(dateIn);
        if (dateIn.value < dateIn.min) {
          showError(errEl, "Date cannot be in the past.");
          return;
        }
        var body = {
          edit_suite_id: sid,
          project_id: pid,
          booked_for_id: fid,
          booking_date: dateIn.value,
          start_time: startIn ? startIn.value : "09:00",
          is_full_day: !!(fullDay && fullDay.checked),
          notes: (notesTa && notesTa.value) || "",
        };
        if (!body.is_full_day && endIn) body.end_time = endIn.value;
        if (submitBtn) submitBtn.disabled = true;
        fetch(listUrl, {
          method: "POST",
          headers: JSON_ACCEPT,
          credentials: "same-origin",
          body: JSON.stringify(body),
        })
          .then(function (r) {
            return r.text().then(function (txt) {
              var j = {};
              if (txt) {
                try {
                  j = JSON.parse(txt);
                } catch (e) {
                  j = {
                    message:
                      "Server returned a non-JSON response (" +
                      r.status +
                      "). If this persists, check the server log.",
                  };
                }
              }
              return { ok: r.ok, j: j };
            });
          })
          .then(function (x) {
            if (submitBtn) submitBtn.disabled = false;
            if (!x.ok) {
              showError(
                errEl,
                (x.j && x.j.message) ||
                  (x.j && x.j.error === "conflict" ? "That slot overlaps another booking." : "Could not book.")
              );
              return;
            }
            if (okEl) {
              okEl.textContent = "Saved. Your lists below are updated.";
              okEl.hidden = false;
            }
            refreshLists();
            bumpDashboardIfToday(x.j && x.j.booking);
          })
          .catch(function () {
            if (submitBtn) submitBtn.disabled = false;
            showError(errEl, "Network error.");
          });
      });
    }

    wireFullDay(editFull, editEnd, editEndWrap);
    var closeBtn = document.getElementById("booking-edit-close-btn");
    if (closeBtn) {
      closeBtn.addEventListener("click", function () {
        if (window.tmShell) window.tmShell.closeInspector();
      });
    }

    var btnList = document.getElementById("booking-view-list");
    var btnTimeline = document.getElementById("booking-view-timeline");
    if (btnList) {
      btnList.addEventListener("click", function () {
        setViewMode(false);
      });
    }
    if (btnTimeline) {
      btnTimeline.addEventListener("click", function () {
        setViewMode(true);
      });
    }
    if (dateIn) {
      dateIn.addEventListener("change", function () {
        if (bookingPageSection && bookingPageSection.classList.contains("is-timeline")) {
          renderTimeline();
        }
      });
    }
    if (editForm) {
      editForm.addEventListener("submit", function (e) {
        e.preventDefault();
        showError(editErr, "");
        var id = parseInt(editId.value, 10);
        if (!id) return;
        setMinDate(editDate);
        if (editDate.value < editDate.min) {
          showError(editErr, "Date cannot be in the past.");
          return;
        }
        var body = {
          edit_suite_id: parseInt(editSuite.value, 10),
          project_id: parseInt(editProject.value, 10),
          booked_for_id: parseInt(editBookedFor.value, 10),
          booking_date: editDate.value,
          start_time: editStart.value,
          is_full_day: editFull.checked,
          notes: (editNotes && editNotes.value) || "",
        };
        if (!body.is_full_day) body.end_time = editEnd.value;
        fetch(listUrl.replace(/\/?$/, "") + "/" + id, {
          method: "PUT",
          headers: JSON_ACCEPT,
          credentials: "same-origin",
          body: JSON.stringify(body),
        })
          .then(function (r) {
            return r.json().then(function (j) {
              return { ok: r.ok, j: j };
            });
          })
          .then(function (x) {
            if (!x.ok) {
              showError(
                editErr,
                (x.j && x.j.message) ||
                  (x.j && x.j.error === "conflict" ? "That slot overlaps another booking." : "Could not save.")
              );
              return;
            }
            if (window.tmShell) window.tmShell.closeInspector();
            refreshLists();
            bumpDashboardIfToday(x.j && x.j.booking);
          })
          .catch(function () {
            showError(editErr, "Network error.");
          });
      });
    }

    loadMeta(function () {
      refreshLists();
    });
  }

  function initControlSuites() {
    var listEl = document.getElementById("edit-suites-list");
    var emptyEl = document.getElementById("edit-suites-empty");
    var errEl = document.getElementById("edit-suites-error");
    var addBtn = document.getElementById("edit-suite-add-btn");
    var modal = document.getElementById("edit-suite-modal");
    var modalTitle = document.getElementById("edit-suite-modal-title");
    var nameInput = document.getElementById("edit-suite-name");
    var saveBtn = document.getElementById("edit-suite-save");
    var cancelBtn = document.getElementById("edit-suite-cancel");
    var editingId = null;
    var base = (addBtn && addBtn.getAttribute("data-api-base")) || "/booking/edit-suites";
    if (!listEl || !modal) return;

    function toggleEmpty(n) {
      if (emptyEl) emptyEl.hidden = n > 0;
    }

    var suiteOpts = {
      admin: true,
      onEdit: function (s) {
        editingId = s.id;
        if (modalTitle) modalTitle.textContent = "Edit suite";
        if (nameInput) nameInput.value = s.name || "";
        if (modal.showModal) modal.showModal();
      },
      onDelete: function (s) {
        if (!s.is_active) return;
        if (!window.confirm("Deactivate this suite? It will no longer appear for new bookings.")) return;
        fetch(base + "/" + s.id, {
          method: "DELETE",
          headers: { Accept: "application/json" },
          credentials: "same-origin",
        })
          .then(function (r) {
            return r.json().then(function (j) {
              return { ok: r.ok, j: j };
            });
          })
          .then(function (x) {
            if (!x.ok) {
              showError(errEl, (x.j && x.j.message) || "Could not delete.");
              return;
            }
            load();
          })
          .catch(function () {
            showError(errEl, "Network error.");
          });
      },
    };

    function load() {
      showError(errEl, "");
      fetch(base + "?all=1", { headers: { Accept: "application/json" }, credentials: "same-origin" })
        .then(function (r) {
          return r.json();
        })
        .then(function (j) {
          var suites = (j && j.suites) || [];
          toggleEmpty(suites.length);
          renderSuites(listEl, suites, suiteOpts);
        })
        .catch(function () {
          showError(errEl, "Could not load suites.");
        });
    }

    function closeModal() {
      editingId = null;
      if (modal) modal.close();
      if (nameInput) nameInput.value = "";
    }

    if (addBtn) {
      addBtn.addEventListener("click", function () {
        editingId = null;
        if (modalTitle) modalTitle.textContent = "Add suite";
        if (nameInput) nameInput.value = "";
        if (modal.showModal) modal.showModal();
      });
    }
    if (cancelBtn) cancelBtn.addEventListener("click", closeModal);
    if (saveBtn) {
      saveBtn.addEventListener("click", function () {
        var name = (nameInput && nameInput.value.trim()) || "";
        if (!name) return;
        showError(errEl, "");
        if (editingId == null) {
          fetch(base, {
            method: "POST",
            headers: JSON_ACCEPT,
            credentials: "same-origin",
            body: JSON.stringify({ name: name }),
          })
            .then(function (r) {
              return r.json().then(function (j) {
                return { ok: r.ok, j: j };
              });
            })
            .then(function (x) {
              if (!x.ok) {
                showError(errEl, (x.j && x.j.message) || "Could not add.");
                return;
              }
              closeModal();
              load();
            })
            .catch(function () {
              showError(errEl, "Network error.");
            });
        } else {
          fetch(base + "/" + editingId, {
            method: "PUT",
            headers: JSON_ACCEPT,
            credentials: "same-origin",
            body: JSON.stringify({ name: name }),
          })
            .then(function (r) {
              return r.json().then(function (j) {
                return { ok: r.ok, j: j };
              });
            })
            .then(function (x) {
              if (!x.ok) {
                showError(errEl, (x.j && x.j.message) || "Could not save.");
                return;
              }
              closeModal();
              load();
            })
            .catch(function () {
              showError(errEl, "Network error.");
            });
        }
      });
    }

    load();
  }

  document.addEventListener("DOMContentLoaded", function () {
    initDashboardCard();
    var root = document.getElementById("booking-page-root");
    if (root) initBookingPage(root);
    if (document.getElementById("edit-suites-list")) initControlSuites();
  });

  window.renderSuites = renderSuites;
  window.renderBookings = renderBookings;
  window.renderDashboardBooking = renderDashboardBooking;
})();
