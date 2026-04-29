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
  var selectedRoot = false;
  var boardViewMode = "board";
  var boardFilter = "all";
  var boardSort = "scene";
  var boardSearch = "";
  var shotId = null;
  var selectedVersionId = null;
  var replyParentId = null;

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
    html += "</span></summary>";
    html += '<div class="vfx-tree-children">';

    (payload.groups || []).forEach(function (grp) {
      var allScenes = grp.scenes || [];
      var scenes = allScenes.filter(scenePassesFilter);
      var showGroup = allScenes.length > 0 || (payload.isTv && allScenes.length === 0);
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
        html += "</div>";
      });
      html += "</div></details>";
    });

    html += "</div></details></div>";
    root.innerHTML = html;
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
        fetch("/projects/" + projectId + "/vfx/api/scenes/create", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({ group_key: gk }),
        })
          .then(function (r) {
            return r.json();
          })
          .then(function (data) {
            if (!data.ok) {
              var msg =
                data.error === "no_shooting_day"
                  ? "Create a shooting day on Production first."
                  : data.error === "no_episodes_configured"
                    ? "Set number of episodes on the project first."
                    : data.error || "Could not add scene";
              window.alert(msg);
              return;
            }
            if (data.payload) mergePayload(data.payload);
            renderAll();
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
            '<div class="scene-preview-media-wrap"><video class="vfx-main-preview" controls playsinline src="' +
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
    var delPreview = $("[data-scene-preview-delete]");
    if (delPreview) {
      delPreview.addEventListener("click", function () {
        var rid = parseInt(delPreview.getAttribute("data-scene-preview-delete"), 10);
        if (!rid) return;
        if (!window.confirm("Remove this preview video?")) return;
        deleteSceneReference(rid);
      });
    }
    var need = sc.needsVfx;
    document.querySelectorAll("[data-vfx-add-shot]").forEach(function (b) {
      b.disabled = !need;
    });
    document.querySelectorAll("[data-vfx-bulk]").forEach(function (b) {
      b.disabled = !need;
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
      tdCode.innerHTML = escapeHtml(sh.shotCode) + (sh.shotRefFrame ? ' <button type="button" class="vfx-inline-btn" title="Ref frame">🖼</button>' : "");
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
          if (sh.shotRefFrameUrl) openModal(sh.shotRefFrameUrl, !!sh.shotRefFrameIsVideo);
        });
      }
      tr.appendChild(tdCode);

      var tdDep = document.createElement("td");
      tdDep.textContent = deptLabel(sh.department);
      tr.appendChild(tdDep);

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
    var dep = $("#vfx-right-department");
    if (dep) {
      dep.innerHTML = "";
      (payload.departments || ["animation", "fx", "comp"]).forEach(function (opt) {
        var o = document.createElement("option");
        o.value = opt;
        o.textContent = deptLabel(opt);
        if (opt === (shot.department || "animation")) o.selected = true;
        dep.appendChild(o);
      });
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

  function wireMidActions() {
    function addShot() {
      if (!sceneId) return;
      var sc = sceneById(sceneId);
      if (!sc || !sc.needsVfx) return;
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
      if (!sc || !sc.needsVfx) return;
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
    var dep = $("#vfx-right-department");
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
    if (dep) dep.addEventListener("change", function () {
      patch({ department: dep.value });
    });
    var appr = $("#vfx-btn-approve");
    if (appr) appr.addEventListener("click", function () {
      patch({ status: "approved" });
    });

    var vf = $("#vfx-version-file");
    var vimg = $("#vfx-version-url");
    var vcom = $("#vfx-version-comment");
    var vsub = $("#vfx-version-submit");
    if (vsub)
      vsub.addEventListener("click", function () {
        if (!shotId) return;
        if (vf && vf.files && vf.files.length) {
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
              if (vf) vf.value = "";
              if (data.ok && data.payload) mergePayload(data.payload);
              var sh = currentShot();
              if (sh && sh.versions && sh.versions.length) {
                selectedVersionId = sh.versions[sh.versions.length - 1].id;
              }
              renderAll();
            });
        } else {
          var img = (vimg && vimg.value.trim()) || "";
          if (!img) return;
          fetch("/projects/" + projectId + "/vfx/api/shots/" + shotId + "/versions", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            credentials: "same-origin",
            body: JSON.stringify({ image: img, comment: (vcom && vcom.value) || "" }),
          })
            .then(function (r) {
              return r.json();
            })
            .then(function (data) {
              if (vimg) vimg.value = "";
              if (data.ok && data.payload) mergePayload(data.payload);
              var sh = currentShot();
              if (sh && sh.versions && sh.versions.length) {
                selectedVersionId = sh.versions[sh.versions.length - 1].id;
              }
              renderAll();
            });
        }
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
  wireRightActions();
  wireSceneEditing();
  wireKeyboard();
  var f0 = document.querySelector('[data-vfx-filter="all"]');
  if (f0) f0.classList.add("vfx-filter-btn--active");
  renderAll();
})();
