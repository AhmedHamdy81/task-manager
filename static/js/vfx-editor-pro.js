/**
 * 3-panel VFX editor: hierarchy (left), scene + shots (mid), preview + review (right).
 */
(function () {
  var boot = document.getElementById("vfx-editor-bootstrap");
  if (!boot || !boot.textContent) return;

  var payload = JSON.parse(boot.textContent);
  var projectId = window.__VFX_PROJECT_ID__;
  var directoryUserId = window.__VFX_DIRECTORY_USER_ID__;

  var filter = "all";
  var sceneId = null;
  var selectedGroupKey = null;
  var selectedRoot = true;
  var boardViewMode = "board";
  var boardFilter = "all";
  var boardSort = "scene";
  var boardSearch = "";
  var shotId = null;
  var selectedVersionId = null;
  var replyParentId = null;
  var capturedFrameDataUrl = "";
  var pendingSceneCreateGroupKey = null;

  function $(sel, root) {
    return (root || document).querySelector(sel);
  }

  function mergePayload(next) {
    if (!next || !next.scenes) return;
    payload = next;
    if (sceneId) {
      var sc = payload.scenes.find(function (s) {
        return s.id === sceneId;
      });
      if (!sc) sceneId = null;
      else {
        selectedGroupKey = sc.groupKey;
        selectedRoot = false;
      }
    }
    if (shotId && sceneId) {
      var sc2 = payload.scenes.find(function (s) {
        return s.id === sceneId;
      });
      var sh = sc2 && sc2.shots ? sc2.shots.find(function (x) {
        return x.id === shotId;
      }) : null;
      if (!sh) shotId = null;
    }
  }

  function sceneById(id) {
    return payload.scenes.find(function (s) {
      return s.id === id;
    });
  }

  function selectedGroup() {
    if (selectedGroupKey == null) return null;
    return (payload.groups || []).find(function (g) {
      return parseInt(g.key, 10) === parseInt(selectedGroupKey, 10);
    }) || null;
  }

  function currentShot() {
    var sc = sceneById(sceneId);
    if (!sc || !sc.shots) return null;
    return sc.shots.find(function (s) {
      return s.id === shotId;
    });
  }

  function statusEmoji(st) {
    var s = (st || "pending").toLowerCase();
    if (s === "approved") return "🟢";
    if (s === "pending") return "🔴";
    return "🟡";
  }

  function statusLabel(st) {
    return (st || "pending").replace(/\b\w/g, function (c) {
      return c.toUpperCase();
    });
  }

  function deptLabel(d) {
    var m = { animation: "Animation", fx: "FX", comp: "Comp" };
    return m[(d || "animation").toLowerCase()] || d;
  }

  function scenePassesFilter(sc) {
    if (filter === "needs_vfx") return sc.needsVfx;
    if (filter === "in_review") return sc.hasReviewShot;
    return true;
  }

  function vfmt(n) {
    return "v" + String(n || 0).padStart(3, "0");
  }

  function folderSvg() {
    return (
      '<svg class="vfx-tree-svg" viewBox="0 0 20 16" width="16" height="13" aria-hidden="true" focusable="false">' +
      '<path fill="currentColor" d="M0 4c0-1.1.9-2 2-2h5.2c.4 0 .8.2 1 .5L10 5h8c1.1 0 2 .9 2 2v7c0 1.1-.9 2-2 2H2c-1.1 0-2-.9-2-2V4zm2 0v9h16V7h-9.1L9.2 5H2v-1z"/>' +
      "</svg>"
    );
  }

  function sceneSvg() {
    return (
      '<svg class="vfx-tree-svg vfx-tree-svg--scene" viewBox="0 0 14 18" width="12" height="15" aria-hidden="true" focusable="false">' +
      '<path fill="currentColor" d="M1 0h7.5L13 4.5V18H1V0zm1 1v16h10V5H8V1H2zm6 0.4V4h2.6L8 1.4z"/>' +
      "</svg>"
    );
  }

  function submitSceneCreate(groupKey, sceneLabel) {
    return fetch("/projects/" + projectId + "/vfx/api/scenes/create", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({ group_key: groupKey, scene_label: sceneLabel || "" }),
    }).then(function (r) {
      return r.json();
    });
  }

  function reelCreate(label) {
    return fetch("/projects/" + projectId + "/vfx/api/reels/create", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({ label: label || "" }),
    }).then(function (r) {
      return r.json();
    });
  }

  function reelRename(groupKey, label) {
    return fetch("/projects/" + projectId + "/vfx/api/reels/" + groupKey + "/rename", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({ label: label || "" }),
    }).then(function (r) {
      return r.json();
    });
  }

  function reelDelete(groupKey) {
    return fetch("/projects/" + projectId + "/vfx/api/reels/" + groupKey + "/delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: "{}",
    }).then(function (r) {
      return r.json();
    });
  }

  function sceneMoveToReel(sceneIdToMove, groupKey) {
    return fetch("/projects/" + projectId + "/vfx/api/scenes/" + sceneIdToMove + "/move-reel", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({ group_key: groupKey }),
    }).then(function (r) {
      return r.json();
    });
  }

  function openSceneCreateModal(groupKey) {
    var dlg = document.getElementById("vfx-scene-create-modal");
    var input = $("#vfx-scene-create-input");
    var msg = $("#vfx-scene-create-msg");
    if (!dlg || !input) return;
    pendingSceneCreateGroupKey = groupKey;
    input.value = "";
    if (msg) msg.textContent = "";
    if (typeof dlg.showModal === "function") dlg.showModal();
    window.requestAnimationFrame(function () {
      input.focus();
      input.select();
    });
  }

  function renderLeft() {
    var root = $("#vfx-left-tree");
    if (!root) return;
    var canAddScene = !!payload.hasShootingDays;
    var rootActive = selectedRoot && !sceneId ? " vfx-group-name--active" : "";
    var html = '<div class="vfx-tree" role="tree">';
    html += '<details class="vfx-tree-branch" open>';
    html += '<summary class="vfx-tree-folder vfx-tree-folder--root">';
    html += '<span class="vfx-tree-folder-row">';
    html += '<span class="vfx-tree-chevron" aria-hidden="true"></span>';
    html += '<span class="vfx-tree-icon vfx-tree-icon--folder">' + folderSvg() + "</span>";
    html += '<span class="vfx-tree-name vfx-group-select' + rootActive + '" data-vfx-root-select="1">Root</span>';
    if (!payload.isTv) {
      html +=
        '<button type="button" class="vfx-tree-action vfx-tree-action--add" data-vfx-add-reel="1" title="Add reel">+</button>';
    }
    html += "</span></summary>";
    html += '<div class="vfx-tree-children">';

    (payload.groups || []).forEach(function (grp) {
      var allScenes = grp.scenes || [];
      var scenes = allScenes.filter(scenePassesFilter);
      // TV: show episode folders even when empty. Non-TV: show every reel (including new empty reels).
      var showGroup =
        !payload.isTv || allScenes.length > 0 || (payload.isTv && allScenes.length === 0);
      if (!showGroup) return;
      var groupActive = selectedGroupKey === grp.key && !sceneId ? " vfx-group-name--active" : "";
      var addDisabled = !canAddScene ? " disabled" : "";
      var addTitle = canAddScene ? "Add scene" : "Add a shooting day under Production first";
      html += '<details class="vfx-tree-branch vfx-tree-branch--group" open>';
      html += '<summary class="vfx-tree-folder vfx-tree-folder--group">';
      html += '<span class="vfx-tree-folder-row">';
      html += '<span class="vfx-tree-chevron" aria-hidden="true"></span>';
      html += '<span class="vfx-tree-icon vfx-tree-icon--folder">' + folderSvg() + "</span>";
      html +=
        '<span class="vfx-tree-name vfx-group-select' +
        groupActive +
        '" data-vfx-group-key="' +
        grp.key +
        '">' +
        escapeHtml(grp.label) +
        "</span>";
      html +=
        '<button type="button" class="vfx-tree-action vfx-tree-action--add" data-vfx-add-scene="' +
        grp.key +
        '"' +
        addDisabled +
        ' title="' +
        escapeHtml(addTitle) +
        '">+</button>';
      if (!payload.isTv) {
        html +=
          '<button type="button" class="vfx-tree-action vfx-tree-action--rename" data-vfx-rename-reel="' +
          grp.key +
          '" data-vfx-reel-label="' +
          escapeHtml(String(grp.label || "")).replace(/"/g, "&quot;") +
          '" title="Rename reel">✎</button>';
        html +=
          '<button type="button" class="vfx-tree-action vfx-tree-action--remove" data-vfx-remove-reel="' +
          grp.key +
          '" title="Remove reel">×</button>';
      }
      html += "</span></summary>";
      html += '<div class="vfx-tree-children vfx-tree-children--nested">';
      if (allScenes.length === 0) {
        html += '<p class="muted vfx-tree-empty-hint">No scenes yet.</p>';
      } else if (scenes.length === 0) {
        html += '<p class="muted vfx-tree-empty-hint">No scenes match this filter.</p>';
      }
      scenes.forEach(function (sc) {
        var active = sc.id === sceneId ? " vfx-scene-item--active" : "";
        var dotClass =
          sc.aggregateDot === "approved"
            ? "vfx-dot--approved"
            : sc.aggregateDot === "review"
              ? "vfx-dot--review"
              : "vfx-dot--pending";
        html += '<div class="vfx-tree-scene-block">';
        html +=
          '<button type="button" class="vfx-scene-item vfx-tree-scene' +
          active +
          '" data-scene-id="' +
          sc.id +
          '">';
        html += '<span class="vfx-tree-scene-row">';
        html += '<span class="vfx-tree-lead" aria-hidden="true"></span>';
        html += '<span class="vfx-tree-icon vfx-tree-icon--scene">' + sceneSvg() + "</span>";
        html += '<span class="vfx-tree-scene-text">';
        html += '<span class="vfx-scene-item-title">Scene ' + escapeHtml(String(sc.sceneDisplayNumber)) + "</span>";
        html += '<span class="vfx-scene-item-meta">';
        html += '<span class="vfx-dot ' + dotClass + '" title=""></span>';
        html += '<span class="vfx-shot-count">' + sc.shotCount + " shots</span>";
        html += "</span></span></span></button>";
        html +=
          '<button type="button" class="vfx-tree-action vfx-tree-action--remove" data-vfx-remove-scene="' +
          sc.id +
          '" title="Remove scene" aria-label="Remove scene">×</button>';
        if (!payload.isTv) {
          html +=
            '<button type="button" class="vfx-tree-action vfx-tree-action--move" data-vfx-move-scene="' +
            sc.id +
            '" data-vfx-current-group="' +
            sc.groupKey +
            '" title="Move to another reel" aria-label="Move scene">⇄</button>';
        }
        html += "</div>";
      });
      html += "</div></details>";
    });

    html += "</div></details></div>";
    root.innerHTML = html;
    // Prevent <details> toggling when clicking controls inside <summary>.
    root.querySelectorAll("summary .vfx-tree-action").forEach(function (btn) {
      btn.addEventListener("mousedown", function (e) {
        e.preventDefault();
        e.stopPropagation();
      });
    });
    root.querySelectorAll("[data-scene-id]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        sceneId = parseInt(btn.getAttribute("data-scene-id"), 10);
        var sc = sceneById(sceneId);
        selectedGroupKey = sc ? sc.groupKey : null;
        selectedRoot = false;
        shotId = null;
        selectedVersionId = null;
        renderAll();
      });
    });
    root.querySelectorAll("[data-vfx-group-key]").forEach(function (el) {
      el.addEventListener("click", function (e) {
        e.preventDefault();
        e.stopPropagation();
        var gk = parseInt(el.getAttribute("data-vfx-group-key"), 10);
        if (isNaN(gk)) return;
        selectedGroupKey = gk;
        selectedRoot = false;
        sceneId = null;
        shotId = null;
        selectedVersionId = null;
        renderAll();
      });
    });
    root.querySelectorAll("[data-vfx-root-select]").forEach(function (el) {
      el.addEventListener("click", function (e) {
        e.preventDefault();
        e.stopPropagation();
        selectedRoot = true;
        selectedGroupKey = null;
        sceneId = null;
        shotId = null;
        selectedVersionId = null;
        renderAll();
      });
    });
    root.querySelectorAll("[data-vfx-add-scene]").forEach(function (btn) {
      btn.addEventListener("click", function (e) {
        e.preventDefault();
        e.stopPropagation();
        if (btn.disabled) return;
        var gk = parseInt(btn.getAttribute("data-vfx-add-scene"), 10);
        if (isNaN(gk)) return;
        openSceneCreateModal(gk);
      });
    });
    root.querySelectorAll("[data-vfx-add-reel]").forEach(function (btn) {
      btn.addEventListener("click", function (e) {
        e.preventDefault();
        e.stopPropagation();
        var name = window.prompt("New reel name:", "");
        if (name == null) return;
        reelCreate((name || "").trim())
          .then(function (data) {
            if (!data.ok) {
              window.alert(data.error || "Could not add reel.");
              return;
            }
            if (data.payload) mergePayload(data.payload);
            renderAll();
          })
          .catch(function () {
            window.alert("Could not add reel.");
          });
      });
    });
    root.querySelectorAll("[data-vfx-rename-reel]").forEach(function (btn) {
      btn.addEventListener("click", function (e) {
        e.preventDefault();
        e.stopPropagation();
        var gk = parseInt(btn.getAttribute("data-vfx-rename-reel"), 10);
        if (isNaN(gk)) return;
        var oldLabel = btn.getAttribute("data-vfx-reel-label") || "";
        var name = window.prompt("Rename reel:", oldLabel);
        if (name == null) return;
        name = (name || "").trim();
        if (!name) return;
        reelRename(gk, name)
          .then(function (data) {
            if (!data.ok) {
              window.alert(data.error || "Could not rename reel.");
              return;
            }
            if (data.payload) mergePayload(data.payload);
            renderAll();
          })
          .catch(function () {
            window.alert("Could not rename reel.");
          });
      });
    });
    root.querySelectorAll("[data-vfx-remove-reel]").forEach(function (btn) {
      btn.addEventListener("click", function (e) {
        e.preventDefault();
        e.stopPropagation();
        var gk = parseInt(btn.getAttribute("data-vfx-remove-reel"), 10);
        if (isNaN(gk)) return;
        if (!window.confirm("Remove this reel? Reel must be empty.")) return;
        reelDelete(gk)
          .then(function (data) {
            if (!data.ok) {
              var msg = data.error === "reel_not_empty" ? "Reel is not empty. Move scenes first." : data.error;
              window.alert(msg || "Could not remove reel.");
              return;
            }
            if (data.payload) mergePayload(data.payload);
            if (selectedGroupKey === gk) {
              selectedGroupKey = null;
              selectedRoot = true;
            }
            renderAll();
          })
          .catch(function () {
            window.alert("Could not remove reel.");
          });
      });
    });
    root.querySelectorAll("[data-vfx-move-scene]").forEach(function (btn) {
      btn.addEventListener("click", function (e) {
        e.preventDefault();
        e.stopPropagation();
        var sid = parseInt(btn.getAttribute("data-vfx-move-scene"), 10);
        var cur = parseInt(btn.getAttribute("data-vfx-current-group"), 10);
        if (isNaN(sid) || isNaN(cur)) return;
        var options = (payload.groups || [])
          .map(function (g) {
            return g.key + ": " + g.label;
          })
          .join("\n");
        var raw = window.prompt("Move scene to reel number:\n" + options, String(cur));
        if (raw == null) return;
        var target = parseInt(String(raw).trim(), 10);
        if (isNaN(target) || target < 1 || target === cur) return;
        sceneMoveToReel(sid, target)
          .then(function (data) {
            if (!data.ok) {
              window.alert(data.error || "Could not move scene.");
              return;
            }
            if (data.payload) mergePayload(data.payload);
            renderAll();
          })
          .catch(function () {
            window.alert("Could not move scene.");
          });
      });
    });
    root.querySelectorAll("[data-vfx-remove-scene]").forEach(function (btn) {
      btn.addEventListener("click", function (e) {
        e.preventDefault();
        e.stopPropagation();
        var sid = parseInt(btn.getAttribute("data-vfx-remove-scene"), 10);
        if (isNaN(sid)) return;
        if (
          !window.confirm(
            "Remove this scene from the shooting day? VFX shots, versions, references, and comments will be deleted."
          )
        ) {
          return;
        }
        fetch("/projects/" + projectId + "/shooting-day-scenes/" + sid + "/delete", {
          method: "POST",
          headers: { "X-VFX-Response": "json" },
          credentials: "same-origin",
        })
          .then(function (r) {
            return r.json();
          })
          .then(function (data) {
            if (!data.ok) {
              window.alert("Could not remove scene.");
              return;
            }
            if (sceneId === sid) {
              sceneId = null;
              shotId = null;
              selectedVersionId = null;
            }
            if (data.payload) mergePayload(data.payload);
            renderAll();
          });
      });
    });
  }

  function escapeHtml(s) {
    var d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
  }

  function fmtDate(iso) {
    if (!iso) return "";
    var d = new Date(iso);
    if (isNaN(d.getTime())) return String(iso).slice(0, 10);
    return d.toISOString().slice(0, 10);
  }

  function sceneStats(scn) {
    var shots = scn.shots || [];
    var total = shots.length;
    var approved = 0;
    var review = 0;
    var pending = 0;
    shots.forEach(function (sh) {
      var st = (sh.status || "pending").toLowerCase();
      if (st === "approved") approved += 1;
      else if (st === "review" || st === "sent") review += 1;
      else pending += 1;
    });
    return { total: total, approved: approved, review: review, pending: pending };
  }

  function sceneLaneKey(scn) {
    var stats = sceneStats(scn);
    if (!scn.needsVfx) return "done";
    if (stats.total === 0 || stats.pending === stats.total) return "waiting";
    if (stats.approved === stats.total) return "done";
    if (stats.review > 0) return "review";
    if (stats.pending > 0 && stats.approved === 0) return "ready";
    return "progress";
  }

  function renderSceneInsights(sc) {
    if (!sc) return;
    var st = sceneStats(sc);
    var approvedPct = st.total ? Math.round((st.approved / st.total) * 100) : 0;
    var approvedDeg = Math.round((approvedPct / 100) * 360);

    var approvedText = $("#scene-insights-approved");
    if (approvedText) approvedText.textContent = st.approved + " / " + st.total + " (" + approvedPct + "%)";
    var approvedPie = $("#scene-insights-approved-pie");
    if (approvedPie) {
      approvedPie.style.background =
        "radial-gradient(circle at center, rgba(14, 21, 34, 0.98) 53%, transparent 55%), " +
        "conic-gradient(#3d9a7a 0deg " +
        approvedDeg +
        "deg, rgba(255, 255, 255, 0.14) " +
        approvedDeg +
        "deg 360deg)";
    }

    var inHouse = 0;
    var external = 0;
    (sc.shots || []).forEach(function (sh) {
      if ((sh.vendor || "in_house") === "external") external += 1;
      else inHouse += 1;
    });
    var vendorText = $("#scene-insights-vendor");
    if (vendorText) vendorText.textContent = inHouse + " / " + external;
    var vendorPct = st.total ? Math.round((inHouse / st.total) * 100) : 0;
    var vendorDeg = Math.round((vendorPct / 100) * 360);
    var vendorPie = $("#scene-insights-vendor-pie");
    if (vendorPie) {
      vendorPie.style.background =
        "radial-gradient(circle at center, rgba(14, 21, 34, 0.98) 53%, transparent 55%), " +
        "conic-gradient(#4a8fd9 0deg " +
        vendorDeg +
        "deg, rgba(255, 255, 255, 0.14) " +
        vendorDeg +
        "deg 360deg)";
    }

    var totalEl = $("#scene-insights-status-total");
    if (totalEl) totalEl.textContent = st.total + " total";
    var pendingPct = st.total ? Math.round((st.pending / st.total) * 100) : 0;
    var reviewPct = st.total ? Math.round((st.review / st.total) * 100) : 0;

    var pendingBar = $("#scene-status-pending-bar");
    if (pendingBar) pendingBar.style.width = pendingPct + "%";
    var reviewBar = $("#scene-status-review-bar");
    if (reviewBar) reviewBar.style.width = reviewPct + "%";
    var approvedStatusBar = $("#scene-status-approved-bar");
    if (approvedStatusBar) approvedStatusBar.style.width = approvedPct + "%";

    var pendingCount = $("#scene-status-pending-count");
    if (pendingCount) pendingCount.textContent = String(st.pending);
    var reviewCount = $("#scene-status-review-count");
    if (reviewCount) reviewCount.textContent = String(st.review);
    var approvedCount = $("#scene-status-approved-count");
    if (approvedCount) approvedCount.textContent = String(st.approved);
  }

  function laneLabel(key) {
    var m = {
      waiting: "Waiting/Hold",
      ready: "Ready",
      progress: "In Progress",
      review: "Review",
      done: "Done",
    };
    return m[key] || key;
  }

  function matchesBoardFilter(scn) {
    if (boardFilter === "needs_vfx") return !!scn.needsVfx;
    if (boardFilter === "in_review") return sceneStats(scn).review > 0;
    if (boardFilter === "blocked") return (scn.shots || []).length === 0;
    return true;
  }

  function matchesBoardSearch(scn) {
    if (!boardSearch) return true;
    var q = boardSearch.toLowerCase();
    var text = [
      scn.groupLabel || "",
      "scene " + String(scn.sceneDisplayNumber || ""),
      scn.sceneLabel || "",
    ]
      .join(" ")
      .toLowerCase();
    return text.indexOf(q) >= 0;
  }

  function sortScenesForBoard(arr) {
    arr.sort(function (a, b) {
      if (boardSort === "shots") return (sceneStats(b).total || 0) - (sceneStats(a).total || 0);
      if (boardSort === "review") return (sceneStats(b).review || 0) - (sceneStats(a).review || 0);
      var ga = parseInt(a.groupKey, 10) || 0;
      var gb = parseInt(b.groupKey, 10) || 0;
      if (ga !== gb) return ga - gb;
      return (a.sceneDisplayNumber || 0) - (b.sceneDisplayNumber || 0);
    });
    return arr;
  }

  function pickShot(shot) {
    if (!shot) return;
    shotId = shot.id;
    var vers = shot.versions || [];
    selectedVersionId = vers.length ? vers[vers.length - 1].id : null;
  }

  function patchShot(shotIdToUpdate, body, done) {
    fetch("/projects/" + projectId + "/vfx/api/shots/" + shotIdToUpdate, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify(body || {}),
    })
      .then(function (r) {
        return r.json();
      })
      .then(function (data) {
        if (data.ok && data.payload) mergePayload(data.payload);
        if (typeof done === "function") done(data);
        renderAll();
      });
  }

  function renderSceneCapturePanel(sc) {
    var panel = $("#scene-capture-panel");
    if (!panel) return;
    panel.hidden = true;
    panel.innerHTML = "";
    capturedFrameDataUrl = "";
    if (!sc || !sc.scenePreviewIsVideo || !sc.scenePreviewUrl) return;
    panel.hidden = false;
    var options = ['<option value="">Use for Shot…</option>'];
    (sc.shots || []).forEach(function (sh) {
      options.push(
        '<option value="' +
          sh.id +
          '">' +
          escapeHtml(sh.shotCode || "Shot") +
          "</option>"
      );
    });
    options.push('<option value="__create_new_shot__">Create new shot</option>');
    panel.innerHTML =
      '<div class="scene-capture-actions">' +
      '<button type="button" class="btn btn--small btn--ghost" id="scene-capture-btn">Capture Frame</button>' +
      '<select id="scene-capture-shot-select" class="input input--sm">' +
      options.join("") +
      "</select>" +
      '<button type="button" class="btn btn--small btn--primary" id="scene-capture-assign-btn" disabled>Assign</button>' +
      "</div>" +
      '<div class="scene-capture-preview-wrap">' +
      '<img id="scene-capture-preview" class="scene-capture-preview" alt="Captured frame preview" hidden>' +
      '<p id="scene-capture-msg" class="muted scene-capture-msg"></p>' +
      "</div>";

    var captureBtn = $("#scene-capture-btn");
    var assignBtn = $("#scene-capture-assign-btn");
    var shotSel = $("#scene-capture-shot-select");
    var preview = $("#scene-capture-preview");
    var msg = $("#scene-capture-msg");

    if (captureBtn) {
      captureBtn.addEventListener("click", function () {
        var video = document.getElementById("sceneVideo");
        if (!video || !video.videoWidth || !video.videoHeight) {
          if (msg) msg.textContent = "Play the scene video first, then capture.";
          return;
        }
        var canvas = document.createElement("canvas");
        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
        var ctx = canvas.getContext("2d");
        if (!ctx) return;
        ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
        capturedFrameDataUrl = canvas.toDataURL("image/png");
        if (preview) {
          preview.src = capturedFrameDataUrl;
          preview.hidden = false;
        }
        if (msg) msg.textContent = "Frame captured. Choose a shot (or Create new shot) then Assign.";
        if (assignBtn) assignBtn.disabled = !(shotSel && shotSel.value);
      });
    }

    if (shotSel) {
      shotSel.addEventListener("change", function () {
        if (assignBtn) assignBtn.disabled = !(capturedFrameDataUrl && shotSel.value);
      });
    }

    if (assignBtn) {
      assignBtn.addEventListener("click", function () {
        if (!capturedFrameDataUrl) return;
        var raw = shotSel ? shotSel.value : "";
        if (!raw) return;
        assignBtn.disabled = true;

        function assignToShot(shotId) {
          return fetch("/projects/" + projectId + "/vfx/api/shots/" + shotId + "/ref-frame", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            credentials: "same-origin",
            body: JSON.stringify({ image_data: capturedFrameDataUrl }),
          }).then(function (r) {
            return r.json();
          });
        }

        function finishAssign(data) {
          if (!data.ok) {
            if (msg) msg.textContent = "Could not assign frame.";
            assignBtn.disabled = false;
            return;
          }
          if (data.payload) mergePayload(data.payload);
          if (msg) msg.textContent = "Frame assigned to shot.";
          renderAll();
        }

        if (raw === "__create_new_shot__") {
          fetch("/projects/" + projectId + "/vfx/api/scenes/" + sc.id + "/shots", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            credentials: "same-origin",
            body: JSON.stringify({ department: "animation" }),
          })
            .then(function (r) {
              return r.json();
            })
            .then(function (data) {
              if (!data.ok) {
                if (msg) msg.textContent = data.error || "Could not create shot.";
                assignBtn.disabled = false;
                return;
              }
              if (data.payload) mergePayload(data.payload);
              var newId = data.shotId;
              if (!newId) {
                var scn = sceneById(sc.id);
                if (scn && scn.shots && scn.shots.length) {
                  newId = scn.shots.reduce(function (m, x) {
                    return x.id > m ? x.id : m;
                  }, 0);
                }
              }
              if (!newId) {
                if (msg) msg.textContent = "Shot created but could not assign frame.";
                assignBtn.disabled = false;
                renderAll();
                return;
              }
              return assignToShot(newId).then(finishAssign);
            })
            .catch(function () {
              if (msg) msg.textContent = "Network error.";
              assignBtn.disabled = false;
            });
        } else {
          var sid = parseInt(raw, 10);
          if (!sid) {
            assignBtn.disabled = false;
            return;
          }
          assignToShot(sid)
            .then(finishAssign)
            .catch(function () {
              if (msg) msg.textContent = "Network error.";
              assignBtn.disabled = false;
            });
        }
      });
    }
  }

  function deleteSceneReference(referenceId) {
    if (!referenceId) return;
    fetch("/projects/" + projectId + "/vfx/api/references/" + referenceId + "/delete", {
      method: "POST",
      credentials: "same-origin",
    })
      .then(function (r) {
        return r.json();
      })
      .then(function (data) {
        if (!data.ok) {
          window.alert("Could not delete reference.");
          return;
        }
        if (data.payload) mergePayload(data.payload);
        renderAll();
      });
  }

  function renderSceneBoard(title, scenesInput) {
    var wrap = $("#vfx-episode-previews");
    var titleEl = $("#vfx-board-title");
    if (!wrap) return;
    if (titleEl) titleEl.textContent = title;
    var scenes = (scenesInput || []).filter(matchesBoardFilter).filter(matchesBoardSearch);
    sortScenesForBoard(scenes);
    if (boardViewMode === "list") {
      var htmlList = '<div class="vfx-scene-list">';
      scenes.forEach(function (scn) {
        var st = sceneStats(scn);
        var pct = st.total ? Math.round((st.approved / st.total) * 100) : 0;
        htmlList +=
          '<button type="button" class="vfx-scene-list-row" data-board-scene-id="' +
          scn.id +
          '">' +
          '<span class="vfx-scene-list-main">' +
          escapeHtml((scn.groupLabel || "") + " / Scene " + String(scn.sceneDisplayNumber || "")) +
          "</span>" +
          '<span class="vfx-scene-list-meta">' +
          laneLabel(sceneLaneKey(scn)) +
          " · " +
          st.total +
          " shots · " +
          pct +
          "%</span></button>";
      });
      if (!scenes.length) htmlList += '<p class="muted">No scenes match current filters.</p>';
      htmlList += "</div>";
      wrap.innerHTML = htmlList;
    } else {
      var html = '<div class="vfx-board-grid">';
      scenes.forEach(function (scn) {
        var st = sceneStats(scn);
        var pct = st.total ? Math.round((st.approved / st.total) * 100) : 0;
        var lane = laneLabel(sceneLaneKey(scn));
        var media = scn.scenePreviewUrl
          ? scn.scenePreviewIsVideo
            ? '<video class="vfx-episode-preview-media" src="' + escapeHtml(scn.scenePreviewUrl) + '" muted playsinline></video>'
            : '<img class="vfx-episode-preview-media" src="' + escapeHtml(scn.scenePreviewUrl) + '" alt="">'
          : '<div class="vfx-episode-preview-empty">No preview</div>';
        html += '<button type="button" class="vfx-episode-preview-card" data-board-scene-id="' + scn.id + '">';
        html += '<div class="vfx-card-layout">';
        html += '<div class="vfx-card-media">' + media + "</div>";
        html += '<div class="vfx-card-data">';
        html +=
          '<div class="vfx-episode-preview-head vfx-episode-preview-head--inline">' +
          escapeHtml((scn.groupLabel || "") + " / Scene " + String(scn.sceneDisplayNumber || "")) +
          "</div>";
        html +=
          '<div class="vfx-card-meta">' +
          '<span class="vfx-card-meta-line">' + st.total + " shots · " + st.review + " review</span>" +
          '<span class="vfx-card-meta-line vfx-card-meta-line--status">' + escapeHtml(lane) + "</span>" +
          "</div>";
        html += '<div class="vfx-progress"><span style="width:' + pct + '%"></span></div>';
        html += "</div></div></button>";
      });
      if (!scenes.length) html += '<p class="muted">No scenes match current filters.</p>';
      html += "</div>";
      wrap.innerHTML = html;
    }
    wrap.querySelectorAll("[data-board-scene-id]").forEach(function (el) {
      el.addEventListener("click", function () {
        var sid = parseInt(el.getAttribute("data-board-scene-id"), 10);
        var scn = (payload.scenes || []).find(function (s) {
          return s.id === sid;
        });
        if (!scn) return;
        sceneId = scn.id;
        selectedGroupKey = scn.groupKey;
        selectedRoot = false;
        shotId = null;
        selectedVersionId = null;
        renderAll();
      });
    });
  }

  function renderMid() {
    var empty = $("#vfx-mid-empty");
    var body = $("#vfx-mid-body");
    var episodeBlock = $("#vfx-episode-previews-block");
    var sceneTopBlock = $("#vfx-scene-top-block");
    var refsBlock = $("#vfx-scene-refs-block");
    var shotsBlock = $("#vfx-shots-block");
    if (!sceneId) {
      if (selectedRoot) {
        if (empty) empty.hidden = true;
        if (body) body.hidden = false;
        if (episodeBlock) episodeBlock.hidden = false;
        if (sceneTopBlock) sceneTopBlock.hidden = true;
        if (refsBlock) refsBlock.hidden = true;
        if (shotsBlock) shotsBlock.hidden = true;
        var hdrRoot = $("#vfx-mid-header");
        if (hdrRoot) hdrRoot.textContent = "Root / All Scene Previews";
        document.querySelectorAll("[data-vfx-add-shot],[data-vfx-bulk]").forEach(function (b) {
          b.disabled = true;
        });
        renderSceneBoard("Root Scene Board", (payload.scenes || []).filter(scenePassesFilter));
        return;
      }
      var grp = selectedGroup();
      if (!grp) {
        if (empty) empty.hidden = false;
        if (body) body.hidden = true;
        return;
      }
      if (empty) empty.hidden = true;
      if (body) body.hidden = false;
      if (episodeBlock) episodeBlock.hidden = false;
      if (sceneTopBlock) sceneTopBlock.hidden = true;
      if (refsBlock) refsBlock.hidden = true;
      if (shotsBlock) shotsBlock.hidden = true;
      var hdrGroup = $("#vfx-mid-header");
      if (hdrGroup) hdrGroup.textContent = grp.label + " / All Scene Previews";
      document.querySelectorAll("[data-vfx-add-shot],[data-vfx-bulk]").forEach(function (b) {
        b.disabled = true;
      });
      renderSceneBoard(grp.label + " Scene Board", grp.scenes || []);
      return;
    }
    if (empty) empty.hidden = true;
    if (body) body.hidden = false;
    if (episodeBlock) episodeBlock.hidden = true;
    if (sceneTopBlock) sceneTopBlock.hidden = false;
    if (refsBlock) refsBlock.hidden = false;
    if (shotsBlock) shotsBlock.hidden = false;
    var sc = sceneById(sceneId);
    if (!sc) return;
    var hdr = $("#vfx-mid-header");
    if (hdr) hdr.textContent = sc.groupLabel + " / " + (sc.sceneTitle || ("Scene " + sc.sceneDisplayNumber));
    var comments = $("#scene-comments");
    if (comments) comments.value = sc.sceneNotes || "";
    renderSceneInsights(sc);
    var sp = $("#scene-preview");
    if (sp) {
      if (sc.scenePreviewUrl) {
        var removePreview = "";
        if (sc.scenePreviewReferenceId) {
          removePreview =
            '<button type="button" class="btn btn--small btn--ghost scene-preview-remove" data-scene-preview-delete="' +
            sc.scenePreviewReferenceId +
            '">Remove Preview</button>';
        }
        if (sc.scenePreviewIsVideo) {
          sp.innerHTML =
            '<div class="scene-preview-media-wrap"><video id="sceneVideo" class="vfx-main-preview" controls playsinline src="' +
            escapeHtml(sc.scenePreviewUrl) +
            '"></video>' +
            removePreview +
            "</div>";
        } else {
          sp.innerHTML =
            '<div class="scene-preview-media-wrap"><img class="vfx-main-preview" src="' +
            escapeHtml(sc.scenePreviewUrl) +
            '" alt="">' +
            removePreview +
            "</div>";
        }
      } else {
        sp.innerHTML =
          '<div class="preview-placeholder" id="scene-preview-placeholder">' +
          "<span>No preview</span>" +
          '<button type="button" class="btn btn--small btn--ghost" id="scene-preview-upload-btn">Upload Preview</button>' +
          '<input type="file" id="scene-preview-upload" accept="image/*,video/*" hidden>' +
          "</div>";
      }
    }
    setupScenePreviewUpload();
    renderSceneCapturePanel(sc);
    var delPreview = $("[data-scene-preview-delete]");
    if (delPreview) {
      delPreview.addEventListener("click", function () {
        var rid = parseInt(delPreview.getAttribute("data-scene-preview-delete"), 10);
        if (!rid) return;
        if (!window.confirm("Remove this preview video?")) return;
        deleteSceneReference(rid);
      });
    }
    document.querySelectorAll("[data-vfx-add-shot]").forEach(function (b) {
      b.disabled = false;
    });
    document.querySelectorAll("[data-vfx-bulk]").forEach(function (b) {
      b.disabled = false;
    });

    var refs = $("#vfx-scene-refs");
    if (refs) {
      refs.innerHTML = "";
      (sc.references || []).forEach(function (r) {
        var wrap = document.createElement("div");
        wrap.className = "vfx-ref-tile";
        if (r.isVideo) {
          var v = document.createElement("video");
          v.className = "vfx-ref-preview";
          v.controls = true;
          v.src = r.previewUrl;
          v.setAttribute("playsinline", "");
          wrap.appendChild(v);
        } else {
          var im = document.createElement("img");
          im.className = "vfx-ref-preview";
          im.alt = "";
          im.src = r.previewUrl;
          wrap.appendChild(im);
        }
        if (r.notes) {
          var n = document.createElement("p");
          n.className = "muted vfx-ref-notes";
          n.textContent = r.notes;
          wrap.appendChild(n);
        }
        var del = document.createElement("button");
        del.type = "button";
        del.className = "btn btn--small btn--ghost vfx-ref-delete";
        del.textContent = "Delete";
        del.addEventListener("click", function () {
          if (!window.confirm("Delete this scene reference?")) return;
          deleteSceneReference(r.id);
        });
        wrap.appendChild(del);
        refs.appendChild(wrap);
      });
    }

    var tbody = $("#vfx-shots-tbody");
    if (!tbody) return;
    tbody.innerHTML = "";
    (sc.shots || []).forEach(function (sh) {
      var tr = document.createElement("tr");
      tr.className = "vfx-shot-row vfx-shot-row--" + (sh.department || "animation");
      if (sh.id === shotId) tr.classList.add("vfx-shot-row--selected");

      tr.addEventListener("click", function (e) {
        if (e.target.closest("button,input,select")) return;
        pickShot(sh);
        renderAll();
      });

      var tdCode = document.createElement("td");
      tdCode.className = "vfx-cell-shot-code";
      tdCode.innerHTML =
        escapeHtml(sh.shotCode) +
        (sh.shotRefFrame || sh.shotAnnotation
          ? ' <button type="button" class="vfx-inline-btn" title="Ref frame / annotation">🖼</button>'
          : "");
      tdCode.addEventListener("dblclick", function () {
        var prev = sh.shotCode;
        tdCode.innerHTML = '<input class="input input--sm vfx-inline-input" value="' + escapeHtml(prev) + '">';
        var inp = tdCode.querySelector("input");
        if (!inp) return;
        inp.focus();
        inp.select();
        function save() {
          var v = inp.value.trim();
          if (!v || v === prev) {
            renderMid();
            return;
          }
          patchShot(sh.id, { shot_code: v });
        }
        inp.addEventListener("keydown", function (ev) {
          if (ev.key === "Enter") save();
          if (ev.key === "Escape") renderMid();
        });
        inp.addEventListener("blur", save);
      });
      var refBtn = tdCode.querySelector(".vfx-inline-btn");
      if (refBtn) {
        refBtn.addEventListener("click", function (e) {
          e.stopPropagation();
          pickShot(sh);
          renderAll();
          if (sh.shotRefFrameUrl && !sh.shotRefFrameIsVideo) {
            openAnnotationModal(sh);
          } else {
            var rightBody = $("#vfx-right-body");
            if (rightBody && typeof rightBody.scrollIntoView === "function") {
              rightBody.scrollIntoView({ behavior: "smooth", block: "nearest" });
            }
          }
        });
      }
      tr.appendChild(tdCode);

      var tdVendor = document.createElement("td");
      tdVendor.innerHTML =
        '<select class="input input--sm vfx-inline-select"><option value="in_house">In-house</option><option value="external">External</option></select>' +
        '<input class="input input--sm vfx-inline-input" placeholder="Vendor name" style="display:none">';
      var vendorSel = tdVendor.querySelector("select");
      var vendorName = tdVendor.querySelector("input");
      vendorSel.value = sh.vendor || "in_house";
      vendorName.value = sh.vendorName || "";
      vendorName.style.display = vendorSel.value === "external" ? "block" : "none";
      vendorSel.addEventListener("change", function (e) {
        e.stopPropagation();
        vendorName.style.display = vendorSel.value === "external" ? "block" : "none";
        patchShot(sh.id, { vendor: vendorSel.value, vendor_name: vendorSel.value === "external" ? vendorName.value.trim() : "" });
      });
      vendorName.addEventListener("blur", function () {
        if (vendorSel.value !== "external") return;
        patchShot(sh.id, { vendor: "external", vendor_name: vendorName.value.trim() });
      });
      tr.appendChild(tdVendor);

      var tdVersion = document.createElement("td");
      tdVersion.textContent = vfmt(sh.currentVersion);
      tr.appendChild(tdVersion);

      var tdStatus = document.createElement("td");
      tdStatus.textContent = statusEmoji(sh.status) + " " + statusLabel(sh.status);
      tr.appendChild(tdStatus);

      var tdSent = document.createElement("td");
      tdSent.textContent = fmtDate(sh.sentAt);
      tr.appendChild(tdSent);

      var tdActions = document.createElement("td");
      tdActions.className = "vfx-shot-actions";
      tdActions.innerHTML =
        '<button type="button" class="vfx-inline-btn" title="Upload frame">🖼↑</button>' +
        '<button type="button" class="vfx-inline-btn vfx-inline-btn--danger" title="Delete shot">🗑</button>' +
        '<input type="file" accept="image/*" hidden>';
      var uploadBtn = tdActions.querySelectorAll("button")[0];
      var delBtn = tdActions.querySelectorAll("button")[1];
      var fileIn = tdActions.querySelector("input[type=file]");
      uploadBtn.addEventListener("click", function (e) {
        e.stopPropagation();
        fileIn.click();
      });
      fileIn.addEventListener("change", function () {
        if (!fileIn.files || !fileIn.files.length) return;
        var fd = new FormData();
        fd.append("image_file", fileIn.files[0]);
        fetch("/projects/" + projectId + "/vfx/api/shots/" + sh.id + "/ref-frame", {
          method: "POST",
          credentials: "same-origin",
          body: fd,
        })
          .then(function (r) {
            return r.json();
          })
          .then(function (data) {
            fileIn.value = "";
            if (data.ok && data.payload) mergePayload(data.payload);
            renderAll();
          });
      });
      delBtn.addEventListener("click", function (e) {
        e.stopPropagation();
        if (!window.confirm("Delete this shot and all versions/comments?")) return;
        fetch("/projects/" + projectId + "/vfx/api/shots/" + sh.id + "/delete", {
          method: "POST",
          credentials: "same-origin",
        })
          .then(function (r) {
            return r.json();
          })
          .then(function (data) {
            if (!data.ok) return;
            if (shotId === sh.id) {
              shotId = null;
              selectedVersionId = null;
            }
            if (data.payload) mergePayload(data.payload);
            renderAll();
          });
      });
      tr.appendChild(tdActions);
      tbody.appendChild(tr);
    });
  }

  function renderRight() {
    var empty = $("#vfx-right-empty");
    var body = $("#vfx-right-body");
    var shot = currentShot();
    if (!shot) {
      if (empty) empty.hidden = false;
      if (body) body.hidden = true;
      return;
    }
    if (empty) empty.hidden = true;
    if (body) body.hidden = false;

    var verRow = $("#vfx-version-tabs");
    if (verRow) {
      verRow.innerHTML = "";
      (shot.versions || []).forEach(function (v) {
        var b = document.createElement("button");
        b.type = "button";
        b.className = "vfx-version-tab" + (v.id === selectedVersionId ? " vfx-version-tab--active" : "");
        b.textContent = vfmt(v.versionNumber);
        b.setAttribute("data-version-id", v.id);
        b.addEventListener("click", function () {
          selectedVersionId = v.id;
          renderRight();
        });
        verRow.appendChild(b);
      });
    }

    var ver = (shot.versions || []).find(function (x) {
      return x.id === selectedVersionId;
    });
    if (!ver && shot.versions && shot.versions.length) {
      ver = shot.versions[shot.versions.length - 1];
      selectedVersionId = ver.id;
    }
    var prev = $("#vfx-preview-slot");
    if (prev) {
      prev.innerHTML = "";
      if (ver && ver.previewUrl) {
        if (ver.isVideo) {
          var vid = document.createElement("video");
          vid.className = "vfx-main-preview";
          vid.controls = true;
          vid.src = ver.previewUrl;
          vid.setAttribute("playsinline", "");
          vid.addEventListener("click", function () {
            openModal(ver.previewUrl, true);
          });
          prev.appendChild(vid);
        } else {
          var img = document.createElement("img");
          img.className = "vfx-main-preview";
          img.alt = "";
          img.src = ver.previewUrl;
          img.addEventListener("click", function () {
            openModal(ver.previewUrl, ver.isVideo);
          });
          prev.appendChild(img);
        }
      } else {
        prev.innerHTML = '<p class="muted">No version media yet.</p>';
      }
    }

    var codeEl = $("#vfx-right-shot-code");
    if (codeEl) codeEl.textContent = shot.shotCode;
    var st = $("#vfx-right-status");
    if (st) {
      st.innerHTML = "";
      (payload.statuses || []).forEach(function (opt) {
        var o = document.createElement("option");
        o.value = opt;
        o.textContent = statusLabel(opt);
        if (opt === (shot.status || "pending")) o.selected = true;
        st.appendChild(o);
      });
    }
    var refSlot = $("#vfx-right-ref-frame");
    if (refSlot) {
      if (shot.shotRefFrameUrl) {
        refSlot.hidden = false;
        if (shot.shotRefFrameIsVideo) {
          refSlot.innerHTML =
            '<button type="button" class="vfx-ref-frame-btn" id="vfx-right-ref-open" title="Open reference frame">' +
            '<span aria-hidden="true">🖼</span><span>Reference frame</span></button>';
          var openBtn = $("#vfx-right-ref-open");
          if (openBtn) {
            openBtn.addEventListener("click", function () {
              openModal(shot.shotRefFrameUrl, true);
            });
          }
        } else {
          refSlot.innerHTML =
            '<div class="annotation-wrapper" id="vfx-ann-inline-trigger" role="button" tabindex="0" aria-label="Open full frame editor">' +
            '<img id="shotImage" src="' +
            escapeHtml(shot.shotAnnotationUrl || shot.shotRefFrameUrl) +
            '" alt="Shot reference frame">' +
            "</div>";

          var img = $("#shotImage");
          var trigger = $("#vfx-ann-inline-trigger");
          if (img) {
            var inlineFallbackTried = false;
            img.onerror = function () {
              if (inlineFallbackTried) return;
              inlineFallbackTried = true;
              if (shot.shotRefFrameUrl && img.src !== shot.shotRefFrameUrl) {
                img.src = shot.shotRefFrameUrl;
              }
            };
          }
          if (trigger) {
            trigger.addEventListener("click", function () {
              openAnnotationModal(shot);
            });
            trigger.addEventListener("keydown", function (e) {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                openAnnotationModal(shot);
              }
            });
          }
        }
      } else {
        refSlot.hidden = true;
        refSlot.innerHTML = "";
      }
    }

    renderComments(shot);
  }

  function renderComments(shot) {
    var box = $("#vfx-comments-thread");
    if (!box) return;
    var list = shot.comments || [];
    var byParent = {};
    list.forEach(function (c) {
      var pid = c.parentId == null ? 0 : c.parentId;
      if (!byParent[pid]) byParent[pid] = [];
      byParent[pid].push(c);
    });

    function walk(parentId, depth) {
      var rows = byParent[parentId || 0] || [];
      var html = "";
      rows.forEach(function (c) {
        html += '<div class="vfx-comment-thread-node">';
        html += '<div class="vfx-comment vfx-comment--depth-' + depth + (c.resolved ? " vfx-comment--resolved" : "") + '">';
        html += '<div class="vfx-comment-head"><strong>' + escapeHtml(c.userName) + "</strong>";
        html += '<span class="muted vfx-comment-time">' + escapeHtml(c.createdAt || "") + "</span></div>";
        html += '<div class="vfx-comment-body">' + escapeHtml(c.body) + "</div>";
        if (!c.resolved) {
          html +=
            '<div class="vfx-comment-actions"><button type="button" class="btn btn--small btn--ghost" data-reply="' +
            c.id +
            '">Reply</button>';
          html +=
            '<button type="button" class="btn btn--small btn--ghost" data-resolve="' +
            c.id +
            '">Resolve</button></div>';
        }
        html += "</div>";
        html += walk(c.id, depth + 1);
        html += "</div>";
      });
      return html;
    }
    box.innerHTML = walk(0, 0);
    box.querySelectorAll("[data-reply]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        replyParentId = parseInt(btn.getAttribute("data-reply"), 10);
        var hint = $("#vfx-comment-reply-hint");
        if (hint) hint.textContent = "Replying to comment #" + replyParentId;
      });
    });
    box.querySelectorAll("[data-resolve]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var cid = parseInt(btn.getAttribute("data-resolve"), 10);
        fetch("/projects/" + projectId + "/vfx/api/comments/" + cid + "/resolve", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: "{}",
        })
          .then(function (r) {
            return r.json();
          })
          .then(function (data) {
            if (!data.ok) return;
            var sh = currentShot();
            if (sh && sh.comments) {
              var row = sh.comments.find(function (x) {
                return x.id === cid;
              });
              if (row) row.resolved = true;
            }
            renderRight();
          });
      });
    });
  }

  function openModal(url, isVideo) {
    var dlg = document.getElementById("vfx-preview-modal");
    if (!dlg) return;
    var host = $("#vfx-preview-modal-body");
    if (!host) return;
    host.innerHTML = "";
    if (isVideo) {
      var v = document.createElement("video");
      v.className = "vfx-modal-media";
      v.controls = true;
      v.src = url;
      host.appendChild(v);
    } else {
      var im = document.createElement("img");
      im.className = "vfx-modal-media";
      im.src = url;
      im.alt = "";
      host.appendChild(im);
    }
    if (typeof dlg.showModal === "function") dlg.showModal();
  }

  function openAnnotationModal(shot) {
    if (!shot || !shot.shotRefFrameUrl || shot.shotRefFrameIsVideo) return;
    var dlg = document.getElementById("vfx-preview-modal");
    if (!dlg) return;
    var host = $("#vfx-preview-modal-body");
    if (!host) return;
    host.innerHTML =
      '<div class="vfx-annotation-tools">' +
      '<button type="button" class="btn btn--small btn--ghost" id="vfx-ann-modal-draw">Draw</button>' +
      '<button type="button" class="btn btn--small btn--ghost" id="vfx-ann-modal-erase">Erase</button>' +
      '<button type="button" class="btn btn--small btn--ghost" id="vfx-ann-modal-clear">Clear</button>' +
      '<button type="button" class="btn btn--small btn--primary" id="vfx-ann-modal-save">Save</button>' +
      "</div>" +
      '<p id="vfx-ann-modal-msg" class="muted vfx-ann-msg"></p>' +
      '<div class="annotation-wrapper annotation-wrapper--modal">' +
      '<img id="shotImageModal" src="' +
      escapeHtml(shot.shotAnnotationUrl || shot.shotRefFrameUrl) +
      '" alt="Shot reference frame">' +
      '<canvas id="drawCanvasModal"></canvas>' +
      "</div>";
    if (typeof dlg.showModal === "function") dlg.showModal();

    var img = $("#shotImageModal");
    var canvas = $("#drawCanvasModal");
    var drawBtn = $("#vfx-ann-modal-draw");
    var eraseBtn = $("#vfx-ann-modal-erase");
    var clearBtn = $("#vfx-ann-modal-clear");
    var saveBtn = $("#vfx-ann-modal-save");
    var annMsg = $("#vfx-ann-modal-msg");
    if (!img || !canvas) return;
    var ctx = canvas.getContext("2d");
    var drawing = false;
    var mode = "draw";
    var isShowingSavedAnnotation = !!shot.shotAnnotationUrl;
    var modalFallbackTried = false;

    img.onerror = function () {
      if (modalFallbackTried) return;
      modalFallbackTried = true;
      if (shot.shotRefFrameUrl && img.src !== shot.shotRefFrameUrl) {
        isShowingSavedAnnotation = false;
        img.src = shot.shotRefFrameUrl;
        return;
      }
      if (annMsg) annMsg.textContent = "Could not load image preview.";
    };

    function syncCanvas() {
      var rect = img.getBoundingClientRect();
      if (!rect.width || !rect.height) return;
      canvas.width = Math.round(rect.width);
      canvas.height = Math.round(rect.height);
      canvas.style.width = rect.width + "px";
      canvas.style.height = rect.height + "px";
      if (!isShowingSavedAnnotation && shot.shotAnnotationUrl) {
        var ann = new Image();
        ann.onload = function () {
          if (!ctx) return;
          ctx.clearRect(0, 0, canvas.width, canvas.height);
          ctx.drawImage(ann, 0, 0, canvas.width, canvas.height);
        };
        ann.src = shot.shotAnnotationUrl;
      } else if (ctx) {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
      }
    }

    function pxy(e) {
      var r = canvas.getBoundingClientRect();
      return { x: e.clientX - r.left, y: e.clientY - r.top };
    }
    function begin(e) {
      if (!ctx) return;
      drawing = true;
      var p = pxy(e);
      ctx.beginPath();
      ctx.moveTo(p.x, p.y);
      ctx.lineWidth = mode === "erase" ? 10 : 2;
      ctx.lineCap = "round";
      if (mode === "erase") {
        ctx.globalCompositeOperation = "destination-out";
        ctx.strokeStyle = "rgba(0,0,0,1)";
      } else {
        ctx.globalCompositeOperation = "source-over";
        ctx.strokeStyle = "red";
      }
      e.preventDefault();
    }
    function move(e) {
      if (!drawing || !ctx) return;
      var p = pxy(e);
      ctx.lineTo(p.x, p.y);
      ctx.stroke();
      e.preventDefault();
    }
    function end() {
      drawing = false;
      if (ctx) ctx.closePath();
    }

    img.addEventListener("load", syncCanvas);
    window.requestAnimationFrame(syncCanvas);
    canvas.addEventListener("mousedown", begin);
    canvas.addEventListener("mousemove", move);
    window.addEventListener("mouseup", end);
    canvas.addEventListener("mouseleave", end);
    if (drawBtn) drawBtn.addEventListener("click", function () { mode = "draw"; });
    if (eraseBtn) eraseBtn.addEventListener("click", function () { mode = "erase"; });
    if (clearBtn) {
      clearBtn.addEventListener("click", function () {
        if (!ctx) return;
        ctx.clearRect(0, 0, canvas.width, canvas.height);
      });
    }
    if (saveBtn) {
      saveBtn.addEventListener("click", function () {
        if (annMsg) annMsg.textContent = "Saving...";
        saveBtn.disabled = true;
        var originalFrame = new Image();
        originalFrame.onload = function () {
          var dataUrl = "";
          try {
            var outW = Math.max(1, originalFrame.naturalWidth || originalFrame.width || canvas.width || 1);
            var outH = Math.max(1, originalFrame.naturalHeight || originalFrame.height || canvas.height || 1);
            var merged = document.createElement("canvas");
            merged.width = outW;
            merged.height = outH;
            var mctx = merged.getContext("2d");
            if (mctx) {
              // Always save at original frame resolution.
              mctx.drawImage(originalFrame, 0, 0, outW, outH);
              mctx.drawImage(canvas, 0, 0, outW, outH);
              dataUrl = merged.toDataURL("image/png");
            }
          } catch (eMerge) {
            dataUrl = "";
          }
          if (!dataUrl) dataUrl = canvas.toDataURL("image/png");
          fetch("/projects/" + projectId + "/vfx/api/shots/" + shot.id + "/annotation", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            credentials: "same-origin",
            body: JSON.stringify({ image_data: dataUrl }),
          })
            .then(function (r) {
              return r.json().then(function (j) {
                return { ok: r.ok, j: j || {} };
              });
            })
            .then(function (res) {
              if (!res.ok || !res.j.ok) throw new Error((res.j && (res.j.error || res.j.message)) || "save_failed");
              if (res.j.payload) mergePayload(res.j.payload);
              var refreshed = currentShot();
              var savedUrl = refreshed && refreshed.shotAnnotationUrl ? refreshed.shotAnnotationUrl : "";
              if (savedUrl) {
                var busted = savedUrl + (savedUrl.indexOf("?") >= 0 ? "&" : "?") + "v=" + Date.now();
                var probe = new Image();
                probe.onload = function () {
                  isShowingSavedAnnotation = true;
                  img.src = busted;
                  if (ctx) ctx.clearRect(0, 0, canvas.width, canvas.height);
                };
                probe.onerror = function () {
                  isShowingSavedAnnotation = false;
                  img.src = shot.shotRefFrameUrl;
                  if (annMsg) annMsg.textContent = "Saved, but preview fallback loaded.";
                };
                probe.src = busted;
              }
              if (annMsg) annMsg.textContent = "Annotation saved.";
              renderAll();
            })
            .catch(function (err) {
              if (annMsg) annMsg.textContent = "Save failed: " + (err && err.message ? err.message : "network");
            })
            .finally(function () {
              saveBtn.disabled = false;
            });
        };
        originalFrame.onerror = function () {
          if (annMsg) annMsg.textContent = "Save failed: could not load original frame";
          saveBtn.disabled = false;
        };
        originalFrame.src = shot.shotRefFrameUrl;
      });
    }
  }

  function renderAll() {
    renderLeft();
    renderMid();
    renderRight();
  }

  function wireFilters() {
    ["all", "needs_vfx", "in_review"].forEach(function (key) {
      var btn = document.querySelector('[data-vfx-filter="' + key + '"]');
      if (!btn) return;
      btn.addEventListener("click", function () {
        filter = key;
        document.querySelectorAll("[data-vfx-filter]").forEach(function (b) {
          b.classList.toggle("vfx-filter-btn--active", b.getAttribute("data-vfx-filter") === key);
        });
        renderLeft();
      });
    });
  }

  function wireBoardControls() {
    var f = $("#vfx-board-filter");
    var s = $("#vfx-board-sort");
    var q = $("#vfx-board-search");
    var vb = $("#vfx-view-board");
    var vl = $("#vfx-view-list");
    function repaint() {
      if (vb) vb.classList.toggle("vfx-filter-btn--active", boardViewMode === "board");
      if (vl) vl.classList.toggle("vfx-filter-btn--active", boardViewMode === "list");
      if (sceneId) return;
      if (selectedRoot || selectedGroup()) renderMid();
    }
    if (f) {
      f.addEventListener("change", function () {
        boardFilter = f.value || "all";
        repaint();
      });
    }
    if (s) {
      s.addEventListener("change", function () {
        boardSort = s.value || "scene";
        repaint();
      });
    }
    if (q) {
      q.addEventListener("input", function () {
        boardSearch = (q.value || "").trim();
        repaint();
      });
    }
    if (vb) {
      vb.addEventListener("click", function () {
        boardViewMode = "board";
        repaint();
      });
    }
    if (vl) {
      vl.addEventListener("click", function () {
        boardViewMode = "list";
        repaint();
      });
    }
    repaint();
  }

  function wireReportExport() {
    var openBtn = $("#vfx-report-open");
    var dlg = document.getElementById("vfx-report-modal");
    var cancelBtn = $("#vfx-report-cancel");
    var genBtn = $("#vfx-report-generate");
    var groupSel = $("#vfx-report-group");
    var scenesBox = $("#vfx-report-scenes");
    var shotsBox = $("#vfx-report-shots");
    var msg = $("#vfx-report-msg");
    var optFrames = $("#vfx-report-include-frames");
    var optComments = $("#vfx-report-include-comments");
    var optVersions = $("#vfx-report-include-versions");
    if (!openBtn || !dlg || !groupSel || !scenesBox || !shotsBox || !genBtn) return;

    function setMsg(text) {
      if (msg) msg.textContent = text || "";
    }

    function selectedSceneIds() {
      return Array.from(scenesBox.querySelectorAll('input[type="checkbox"]:checked'))
        .map(function (el) {
          return parseInt(el.value, 10);
        })
        .filter(function (x) {
          return !!x;
        });
    }

    function selectedShotIds() {
      return Array.from(shotsBox.querySelectorAll('input[type="checkbox"]:checked'))
        .map(function (el) {
          return parseInt(el.value, 10);
        })
        .filter(function (x) {
          return !!x;
        });
    }

    function sceneListForGroup(groupRaw) {
      var all = (payload.scenes || []).filter(function (sc) {
        return String(sc.sceneStatus || "").toLowerCase() !== "done";
      });
      if (!groupRaw || groupRaw === "all") return all.slice();
      var gk = parseInt(groupRaw, 10);
      if (!gk) return all.slice();
      return all.filter(function (sc) {
        return parseInt(sc.groupKey, 10) === gk;
      });
    }

    function renderShots() {
      var sids = new Set(selectedSceneIds());
      var scenes = payload.scenes || [];
      var shotRows = [];
      scenes.forEach(function (sc) {
        if (!sids.has(sc.id)) return;
        (sc.shots || []).forEach(function (sh) {
          var sst = String(sh.status || "").toLowerCase();
          if (sst === "approved" || sst === "delivered") return;
          shotRows.push({
            id: sh.id,
            code: sh.shotCode || ("Shot " + sh.id),
            sceneId: sc.id,
            sceneLabel: (sc.groupLabel || "") + " / Scene " + String(sc.sceneDisplayNumber || ""),
          });
        });
      });
      shotRows.sort(function (a, b) {
        return String(a.code).localeCompare(String(b.code));
      });
      if (!shotRows.length) {
        shotsBox.innerHTML = '<p class="muted">No shots in selected scenes.</p>';
        return;
      }
      var html = "";
      shotRows.forEach(function (row) {
        html +=
          '<label class="vfx-report-item">' +
          '<input type="checkbox" value="' +
          row.id +
          '" checked> ' +
          '<span>' +
          escapeHtml(row.code) +
          " <span class=\"muted\">(" +
          escapeHtml(row.sceneLabel) +
          ")</span></span></label>";
      });
      shotsBox.innerHTML = html;
    }

    function renderScenes() {
      var list = sceneListForGroup(groupSel.value);
      list.sort(function (a, b) {
        var ga = parseInt(a.groupKey, 10) || 0;
        var gb = parseInt(b.groupKey, 10) || 0;
        if (ga !== gb) return ga - gb;
        return (a.sceneDisplayNumber || 0) - (b.sceneDisplayNumber || 0);
      });
      if (!list.length) {
        scenesBox.innerHTML = '<p class="muted">No scenes available.</p>';
        shotsBox.innerHTML = '<p class="muted">No shots available.</p>';
        return;
      }
      var html = "";
      list.forEach(function (sc) {
        var activeShotCount = (sc.shots || []).filter(function (sh) {
          var sst = String(sh.status || "").toLowerCase();
          return sst !== "approved" && sst !== "delivered";
        }).length;
        html +=
          '<label class="vfx-report-item">' +
          '<input type="checkbox" value="' +
          sc.id +
          '" checked> ' +
          '<span>' +
          escapeHtml((sc.groupLabel || "") + " / Scene " + String(sc.sceneDisplayNumber || "")) +
          " <span class=\"muted\">(" +
          String(activeShotCount) +
          " active shots)</span></span></label>";
      });
      scenesBox.innerHTML = html;
      scenesBox.querySelectorAll('input[type="checkbox"]').forEach(function (cb) {
        cb.addEventListener("change", renderShots);
      });
      renderShots();
    }

    function renderGroups() {
      var html = '<option value="all">All Episodes / Reels</option>';
      (payload.groups || []).forEach(function (g) {
        html += '<option value="' + g.key + '">' + escapeHtml(g.label || ("Group " + g.key)) + "</option>";
      });
      groupSel.innerHTML = html;
      if (selectedGroupKey) groupSel.value = String(selectedGroupKey);
    }

    function openDialog() {
      renderGroups();
      renderScenes();
      setMsg("");
      if (typeof dlg.showModal === "function") dlg.showModal();
    }

    openBtn.addEventListener("click", openDialog);
    groupSel.addEventListener("change", renderScenes);
    if (cancelBtn) {
      cancelBtn.addEventListener("click", function () {
        if (typeof dlg.close === "function") dlg.close();
      });
    }
    genBtn.addEventListener("click", function () {
      var sceneIds = selectedSceneIds();
      var shotIds = selectedShotIds();
      if (!sceneIds.length) {
        setMsg("Select at least one scene.");
        return;
      }
      if (!shotIds.length) {
        setMsg("Select at least one shot.");
        return;
      }
      setMsg("Generating PDF...");
      genBtn.disabled = true;
      fetch("/projects/" + projectId + "/vfx/report", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({
          group_key: groupSel.value === "all" ? null : parseInt(groupSel.value, 10),
          scene_ids: sceneIds,
          shot_ids: shotIds,
          include_frames: !!(optFrames && optFrames.checked),
          include_comments: !!(optComments && optComments.checked),
          include_versions: !!(optVersions && optVersions.checked),
        }),
      })
        .then(function (r) {
          if (!r.ok) {
            return r.json().then(function (j) {
              throw new Error((j && (j.error || j.message)) || "Could not generate report.");
            }).catch(function () {
              throw new Error("Could not generate report.");
            });
          }
          var disposition = r.headers.get("Content-Disposition") || "";
          return r.blob().then(function (blob) {
            return { blob: blob, disposition: disposition };
          });
        })
        .then(function (out) {
          var filename = "VFX_Report.pdf";
          var m = /filename\*=UTF-8''([^;]+)|filename="?([^"]+)"?/i.exec(out.disposition || "");
          if (m) filename = decodeURIComponent(m[1] || m[2] || filename);
          var url = URL.createObjectURL(out.blob);
          var a = document.createElement("a");
          a.href = url;
          a.download = filename;
          document.body.appendChild(a);
          a.click();
          document.body.removeChild(a);
          URL.revokeObjectURL(url);
          setMsg("");
          if (typeof dlg.close === "function") dlg.close();
        })
        .catch(function (err) {
          setMsg(err && err.message ? err.message : "Could not generate report.");
        })
        .finally(function () {
          genBtn.disabled = false;
        });
    });
  }

  function wireMidActions() {
    function addShot() {
      if (!sceneId) return;
      var sc = sceneById(sceneId);
      if (!sc) return;
      fetch("/projects/" + projectId + "/vfx/api/scenes/" + sceneId + "/shots", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ department: "animation" }),
      })
        .then(function (r) {
          return r.json();
        })
        .then(function (data) {
          if (data.ok && data.payload) mergePayload(data.payload);
          renderAll();
        });
    }
    function bulkShots() {
      if (!sceneId) return;
      var sc = sceneById(sceneId);
      if (!sc) return;
      fetch("/projects/" + projectId + "/vfx/api/scenes/" + sceneId + "/shots/bulk", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ start: 1, end: 10 }),
      })
        .then(function (r) {
          return r.json();
        })
        .then(function (data) {
          if (data.ok && data.payload) mergePayload(data.payload);
          renderAll();
        });
    }
    document.querySelectorAll("[data-vfx-add-shot]").forEach(function (btn) {
      btn.addEventListener("click", addShot);
    });
    document.querySelectorAll("[data-vfx-bulk]").forEach(function (btn) {
      btn.addEventListener("click", bulkShots);
    });

    var pick = $("#vfx-ref-file");
    var upBtn = $("#vfx-ref-upload-btn");
    if (upBtn && pick) {
      upBtn.addEventListener("click", function () {
        pick.click();
      });
      pick.addEventListener("change", function () {
        if (!sceneId || !pick.files || !pick.files.length) return;
        var fd = new FormData();
        fd.append("video_file", pick.files[0]);
        fd.append("notes", ($("#vfx-ref-notes") && $("#vfx-ref-notes").value) || "");
        fetch("/projects/" + projectId + "/vfx/scenes/" + sceneId + "/references", {
          method: "POST",
          headers: { "X-VFX-Response": "json" },
          credentials: "same-origin",
          body: fd,
        })
          .then(function (r) {
            return r.json();
          })
          .then(function (data) {
            pick.value = "";
            if (data.ok && data.payload) mergePayload(data.payload);
            renderAll();
          });
      });
    }
  }

  function wireRightActions() {
    var st = $("#vfx-right-status");
    function patch(body) {
      if (!shotId) return;
      fetch("/projects/" + projectId + "/vfx/api/shots/" + shotId, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify(body),
      })
        .then(function (r) {
          return r.json();
        })
        .then(function (data) {
          if (data.ok && data.payload) mergePayload(data.payload);
          renderAll();
        });
    }
    if (st) st.addEventListener("change", function () {
      patch({ status: st.value });
    });
    var appr = $("#vfx-btn-approve");
    if (appr) appr.addEventListener("click", function () {
      patch({ status: "approved" });
    });

    var vf = $("#vfx-version-file");
    var vcom = $("#vfx-version-comment");
    var vsub = $("#vfx-version-submit");
    var vname = $("#vfx-version-file-name");
    var vmsg = $("#vfx-version-msg");
    function setVersionMsg(text) {
      if (vmsg) vmsg.textContent = text || "";
    }
    function syncVersionFileLabel() {
      if (!vname || !vf) return;
      vname.textContent = vf.files && vf.files.length ? vf.files[0].name : "No file selected";
    }
    if (vf) vf.addEventListener("change", function () {
      setVersionMsg("");
      syncVersionFileLabel();
    });
    if (vsub)
      vsub.addEventListener("click", function () {
        if (!shotId) return;
        if (!vf || !vf.files || !vf.files.length) {
          setVersionMsg("Choose an image or video file first.");
          return;
        }
        setVersionMsg("Uploading…");
        vsub.disabled = true;
        var fd = new FormData();
        fd.append("image_file", vf.files[0]);
        fd.append("comment", (vcom && vcom.value) || "");
        fetch("/projects/" + projectId + "/vfx/api/shots/" + shotId + "/versions", {
          method: "POST",
          credentials: "same-origin",
          body: fd,
        })
          .then(function (r) {
            return r.json();
          })
          .then(function (data) {
            vsub.disabled = false;
            if (vf) vf.value = "";
            syncVersionFileLabel();
            if (!data.ok) {
              setVersionMsg(data.error || "Could not add version.");
              return;
            }
            setVersionMsg("");
            if (data.payload) mergePayload(data.payload);
            var sh = currentShot();
            if (sh && sh.versions && sh.versions.length) {
              selectedVersionId = sh.versions[sh.versions.length - 1].id;
            }
            renderAll();
          })
          .catch(function () {
            vsub.disabled = false;
            setVersionMsg("Network error.");
          });
      });

    var csub = $("#vfx-comment-submit");
    var ctxt = $("#vfx-comment-text");
    if (csub && ctxt)
      csub.addEventListener("click", function () {
        if (!shotId || directoryUserId == null) return;
        var body = ctxt.value.trim();
        if (!body) return;
        fetch("/projects/" + projectId + "/vfx/api/shots/" + shotId + "/comments", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({ body: body, parent_id: replyParentId }),
        })
          .then(function (r) {
            return r.json();
          })
          .then(function (data) {
            if (!data.ok || !data.comment) return;
            ctxt.value = "";
            replyParentId = null;
            var hint = $("#vfx-comment-reply-hint");
            if (hint) hint.textContent = "";
            var sh = currentShot();
            if (sh) {
              if (!sh.comments) sh.comments = [];
              sh.comments.push(data.comment);
            }
            renderRight();
          });
      });

    var mclose = $("#vfx-preview-modal-close");
    var dlg = document.getElementById("vfx-preview-modal");
    if (mclose && dlg)
      mclose.addEventListener("click", function () {
        if (typeof dlg.close === "function") dlg.close();
      });

    var sceneCreateDlg = document.getElementById("vfx-scene-create-modal");
    var sceneCreateInput = $("#vfx-scene-create-input");
    var sceneCreateMsg = $("#vfx-scene-create-msg");
    var sceneCreateCancel = $("#vfx-scene-create-cancel");
    var sceneCreateSubmit = $("#vfx-scene-create-submit");
    if (sceneCreateDlg && sceneCreateSubmit) {
      function closeSceneCreateDialog() {
        if (typeof sceneCreateDlg.close === "function") sceneCreateDlg.close();
      }
      function runSceneCreateSubmit() {
        var gk = pendingSceneCreateGroupKey;
        if (!gk) return;
        var rawName = sceneCreateInput ? (sceneCreateInput.value || "").trim() : "";
        if (!/^\d+$/.test(rawName)) {
          if (sceneCreateMsg) sceneCreateMsg.textContent = "Scene number must contain digits only.";
          if (sceneCreateInput) sceneCreateInput.focus();
          return;
        }
        sceneCreateSubmit.disabled = true;
        if (sceneCreateMsg) sceneCreateMsg.textContent = "Creating...";
        submitSceneCreate(gk, rawName)
          .then(function (data) {
            if (!data.ok) {
              var msg =
                data.error === "no_shooting_day"
                  ? "Create a shooting day on Production first."
                  : data.error === "no_episodes_configured"
                    ? "Set number of episodes on the project first."
                    : data.error === "scene_label_too_long"
                      ? "Scene number is too long."
                      : data.error || "Could not add scene";
              if (sceneCreateMsg) sceneCreateMsg.textContent = msg;
              return;
            }
            if (data.payload) mergePayload(data.payload);
            pendingSceneCreateGroupKey = null;
            closeSceneCreateDialog();
            renderAll();
          })
          .catch(function () {
            if (sceneCreateMsg) sceneCreateMsg.textContent = "Could not add scene.";
          })
          .finally(function () {
            sceneCreateSubmit.disabled = false;
          });
      }
      sceneCreateSubmit.addEventListener("click", runSceneCreateSubmit);
      if (sceneCreateInput) {
        sceneCreateInput.addEventListener("keydown", function (e) {
          if (e.key === "Enter") {
            e.preventDefault();
            runSceneCreateSubmit();
          }
        });
      }
      if (sceneCreateCancel) {
        sceneCreateCancel.addEventListener("click", function () {
          pendingSceneCreateGroupKey = null;
          closeSceneCreateDialog();
        });
      }
      sceneCreateDlg.addEventListener("close", function () {
        if (sceneCreateMsg) sceneCreateMsg.textContent = "";
        if (sceneCreateInput) sceneCreateInput.value = "";
      });
    }
  }

  function wireKeyboard() {
    document.addEventListener("keydown", function (e) {
      if (e.target && (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA" || e.target.tagName === "SELECT"))
        return;
      if (!sceneId || (e.key !== "ArrowUp" && e.key !== "ArrowDown")) return;
      var sc = sceneById(sceneId);
      if (!sc || !sc.shots || !sc.shots.length) return;
      var idx = sc.shots.findIndex(function (s) {
        return s.id === shotId;
      });
      if (e.key === "ArrowDown") idx = Math.min(sc.shots.length - 1, idx < 0 ? 0 : idx + 1);
      else idx = Math.max(0, idx < 0 ? 0 : idx - 1);
      var sh = sc.shots[idx];
      if (!sh) return;
      e.preventDefault();
      shotId = sh.id;
      var vers = sh.versions || [];
      selectedVersionId = vers.length ? vers[vers.length - 1].id : null;
      renderAll();
    });
  }

  function setupScenePreviewUpload() {
    var previewBtn = $("#scene-preview-upload-btn");
    var previewFile = $("#scene-preview-upload");
    if (!previewBtn || !previewFile || previewBtn.dataset.bound === "1") return;
    previewBtn.dataset.bound = "1";
    previewBtn.addEventListener("click", function () {
      previewFile.click();
    });
    previewFile.addEventListener("change", function () {
      if (!sceneId || !previewFile.files || !previewFile.files.length) return;
      var fd = new FormData();
      fd.append("video_file", previewFile.files[0]);
      fd.append("notes", "Scene preview");
      fetch("/projects/" + projectId + "/vfx/scenes/" + sceneId + "/references", {
        method: "POST",
        headers: { "X-VFX-Response": "json" },
        credentials: "same-origin",
        body: fd,
      })
        .then(function (r) {
          return r.json();
        })
        .then(function (data) {
          previewFile.value = "";
          if (data.ok && data.payload) mergePayload(data.payload);
          renderAll();
        });
    });
  }

  function wireSceneEditing() {
    var title = $("#vfx-mid-header");
    if (title) {
      function saveTitle() {
        if (!sceneId) return;
        var sc = sceneById(sceneId);
        if (!sc) return;
        var full = (title.textContent || "").trim();
        var raw = full.replace(/^Eps\d+\s*\/\s*/i, "").replace(/^Reel\d+\s*\/\s*/i, "").replace(/^Scene\s*/i, "").trim();
        if (!raw || raw === (sc.sceneLabel || "").trim()) {
          renderMid();
          return;
        }
        if (!/^\d+$/.test(raw)) {
          window.alert("Scene number must contain digits only.");
          renderMid();
          return;
        }
        fetch("/projects/" + projectId + "/vfx/api/scenes/" + sceneId, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({ scene_label: raw }),
        })
          .then(function (r) {
            return r.json();
          })
          .then(function (data) {
            if (data.ok && data.payload) mergePayload(data.payload);
            renderAll();
          });
      }
      title.addEventListener("keydown", function (e) {
        if (e.key === "Enter") {
          e.preventDefault();
          title.blur();
        }
      });
      title.addEventListener("blur", saveTitle);
    }
    var comments = $("#scene-comments");
    if (comments) {
      comments.addEventListener("blur", function () {
        if (!sceneId) return;
        fetch("/projects/" + projectId + "/vfx/api/scenes/" + sceneId, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({ notes: comments.value || "" }),
        })
          .then(function (r) {
            return r.json();
          })
          .then(function (data) {
            if (data.ok && data.payload) mergePayload(data.payload);
          });
      });
    }
    setupScenePreviewUpload();
  }

  wireFilters();
  wireBoardControls();
  wireMidActions();
  wireReportExport();
  wireRightActions();
  wireSceneEditing();
  wireKeyboard();
  var f0 = document.querySelector('[data-vfx-filter="all"]');
  if (f0) f0.classList.add("vfx-filter-btn--active");
  renderAll();
})();
