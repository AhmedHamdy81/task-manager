/**
 * Single global WaveSurfer instance for Music Library + Project Audio Library.
 * Exposes window.TMGlobalAudio (play, togglePlay, setFileList, …) and window.togglePlay.
 */
(function () {
  "use strict";

  function domReady(fn) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", fn);
    } else {
      fn();
    }
  }

  function isTypingContext() {
    var el = document.activeElement;
    if (!el || el === document.body) return false;
    var tag = (el.tagName || "").toUpperCase();
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
    if (el.isContentEditable) return true;
    return false;
  }

  domReady(function () {
    var container = document.getElementById("global-waveform");
    if (!container || !window.WaveSurfer) {
      return;
    }

    var dock = document.getElementById("tm-global-audio-dock");
    var timeEl = document.getElementById("global-waveform-time");
    var toggleBtn = document.getElementById("tm-global-audio-toggle");
    var volumeSlider = document.getElementById("tm-global-audio-volume");
    var volumeLabel = document.getElementById("tm-global-audio-volume-label");
    var trackTitleEl = document.getElementById("tm-global-audio-track");

    var currentPlayingId = null;
    var currentPlayBtn = null;
    var pendingPlayBtn = null;
    var waveformZoomPxPerSec = 50;
    var loopRegion = null;
    var regionsPlugin = null;

    var fileList = [];
    var currentIndex = -1;
    var lastPlayOpts = {};

    if (window.WaveSurfer.Regions && typeof window.WaveSurfer.Regions.create === "function") {
      regionsPlugin = window.WaveSurfer.Regions.create();
    }

    var ws = window.WaveSurfer.create({
      container: container,
      waveColor: "#555",
      progressColor: "#3D9A7A",
      cursorColor: "#fff",
      height: 72,
      barWidth: 2,
      barGap: 2,
      responsive: true,
      minPxPerSec: waveformZoomPxPerSec,
      plugins: regionsPlugin ? [regionsPlugin] : [],
    });

    function applyVolumeFromSlider() {
      if (!volumeSlider) return;
      var v = parseFloat(volumeSlider.value);
      if (isNaN(v)) v = 0.8;
      try {
        if (typeof ws.setVolume === "function") {
          ws.setVolume(v);
        }
      } catch (_e0) {}
      if (volumeLabel) {
        volumeLabel.textContent = Math.round(v * 100) + "%";
      }
    }

    try {
      if (typeof ws.setVolume === "function") {
        ws.setVolume(0.8);
      }
    } catch (_e0b) {}

    try {
      if (ws.backend && typeof ws.backend.setFilter === "function") {
        var ctx = new window.AudioContext();
        var gainNode = ctx.createGain();
        gainNode.gain.value = 0.8;
        ws.backend.setFilter(gainNode);
      }
    } catch (_e1) {
      /* WaveSurfer v7 often has no setFilter; setVolume is enough */
    }

    if (volumeSlider) {
      volumeSlider.value = "0.8";
      volumeSlider.addEventListener("input", applyVolumeFromSlider);
      applyVolumeFromSlider();
    }

    function setFileList(ids) {
      fileList = (ids || [])
        .map(function (x) {
          return Number(x);
        })
        .filter(function (n) {
          return !isNaN(n) && n > 0;
        });
      if (currentPlayingId !== null) {
        currentIndex = fileList.indexOf(Number(currentPlayingId));
      }
    }

    function syncProjectAudioFileListFromDom() {
      var root = document.querySelector(".project-audio-files");
      if (!root) return;
      var ids = [];
      root.querySelectorAll(".project-audio-file-row:not(.project-audio-row-filtered-out)").forEach(function (row) {
        var id = Number(row.getAttribute("data-file-id") || 0);
        if (id) ids.push(id);
      });
      fileList = ids;
      if (currentPlayingId !== null) {
        currentIndex = fileList.indexOf(Number(currentPlayingId));
      }
    }

    function syncMusicLibraryFileListFromDom() {
      var root = document.getElementById("file-list");
      if (!root) {
        fileList = [];
        currentIndex = -1;
        return;
      }
      var ul = root.classList.contains("music-library-list")
        ? root
        : root.querySelector("ul.music-library-list");
      if (!ul) {
        fileList = [];
        currentIndex = -1;
        return;
      }
      var ids = [];
      ul.querySelectorAll("li[id^='file-']").forEach(function (li) {
        var m = li.id.match(/^file-(\d+)$/);
        if (m) ids.push(Number(m[1]));
      });
      fileList = ids;
      if (currentPlayingId !== null) {
        currentIndex = fileList.indexOf(Number(currentPlayingId));
      }
    }

    function refreshFileListAroundButton(btn) {
      if (!btn) return;
      var row = btn.closest("li.music-library-row, .project-audio-file-row");
      if (!row) return;
      var ul = row.closest("ul.music-library-list, ul.project-audio-file-list");
      if (ul && ul.classList.contains("music-library-list")) {
        var ids = [];
        ul.querySelectorAll("li[id^='file-']").forEach(function (li) {
          var m = li.id.match(/^file-(\d+)$/);
          if (m) ids.push(Number(m[1]));
        });
        if (ids.length) fileList = ids;
        return;
      }
      if (row.closest(".project-audio-files")) {
        syncProjectAudioFileListFromDom();
      }
    }

    function findPlayButtonForFileId(id) {
      var sid = Number(id);
      var row = document.getElementById("file-" + sid);
      if (row) return row.querySelector(".music-library-play");
      return document.querySelector('.project-audio-file-row[data-file-id="' + sid + '"] .project-audio-play-btn');
    }

    function cloneOpts(o) {
      o = o || {};
      return { projectId: o.projectId, fileList: o.fileList };
    }

    function setPlayBtnState(btn, isPlaying) {
      if (!btn) return;
      btn.textContent = isPlaying ? "⏸" : "▶";
      btn.setAttribute("aria-label", isPlaying ? "Pause" : "Play");
    }

    function resetAllListPlayButtons() {
      document.querySelectorAll(".music-library-play, .project-audio-play-btn").forEach(function (b) {
        setPlayBtnState(b, false);
      });
    }

    function syncDockToggle() {
      if (!toggleBtn) return;
      try {
        setPlayBtnState(toggleBtn, ws.isPlaying());
      } catch (_e2) {}
    }

    function resetAllInlineProgress() {
      document.querySelectorAll(".tm-audio-file-progress").forEach(function (p) {
        p.style.width = "0%";
      });
    }

    function clearActiveRows() {
      document.querySelectorAll(".tm-audio-file-row--active").forEach(function (el) {
        el.classList.remove("tm-audio-file-row--active", "tm-audio-file-row--playing");
      });
    }

    function setPlayingGlow(playing) {
      document.querySelectorAll(".tm-audio-file-row--active").forEach(function (el) {
        el.classList.toggle("tm-audio-file-row--playing", !!playing);
      });
    }

    function updateDockTrackTitle(id) {
      if (!trackTitleEl) return;
      if (id == null || id === "") {
        trackTitleEl.textContent = "—";
        trackTitleEl.removeAttribute("title");
        return;
      }
      var sid = String(Number(id));
      if (sid === "NaN" || sid === "0") {
        trackTitleEl.textContent = "—";
        trackTitleEl.removeAttribute("title");
        return;
      }
      var name = "";
      var musicLi = document.getElementById("file-" + sid);
      if (musicLi) {
        name = (musicLi.getAttribute("data-file-name") || "").trim();
        if (!name) {
          var nm = musicLi.querySelector(".file-row-name, .music-library-name");
          if (nm) name = (nm.textContent || "").trim();
        }
      }
      if (!name) {
        var prow = document.querySelector('.project-audio-file-row[data-file-id="' + sid + '"]');
        if (prow) {
          var pn = prow.querySelector(".project-audio-file-name, [data-audio-label]");
          if (pn) name = (pn.textContent || "").trim();
        }
      }
      trackTitleEl.textContent = name || "Track #" + sid;
      trackTitleEl.setAttribute("title", trackTitleEl.textContent);
    }

    function setActiveRow(id) {
      clearActiveRows();
      if (id == null || id === "") return;
      var n = Number(id);
      if (isNaN(n) || n <= 0) return;
      var sid = String(n);
      var musicLi = document.getElementById("file-" + sid);
      if (musicLi) {
        musicLi.classList.add("tm-audio-file-row--active");
      }
      document.querySelectorAll('.project-audio-file-row[data-file-id="' + sid + '"]').forEach(function (row) {
        row.classList.add("tm-audio-file-row--active");
      });
      updateDockTrackTitle(sid);
    }

    function syncActiveRowProgress() {
      if (currentPlayingId == null) return;
      var sid = String(Number(currentPlayingId));
      var row = document.getElementById("file-" + sid);
      if (!row) {
        row = document.querySelector('.project-audio-file-row[data-file-id="' + sid + '"]');
      }
      if (!row || !row.classList.contains("tm-audio-file-row--active")) return;
      var prog = row.querySelector(".tm-audio-file-progress");
      if (!prog) return;
      var dur = Number(ws.getDuration() || 0);
      if (dur <= 0) {
        prog.style.width = "0%";
        return;
      }
      prog.style.width = Math.min(100, Math.max(0, (ws.getCurrentTime() / dur) * 100)) + "%";
    }

    function trackUsage(fileId, action, projectId) {
      if (!fileId || !action) return;
      var payload = {
        file_id: Number(fileId),
        action: String(action),
      };
      if (projectId !== undefined && projectId !== null && projectId !== "") {
        payload.project_id = Number(projectId);
      }
      fetch("/audio/track", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
        },
        body: JSON.stringify(payload),
      }).catch(function () {});
    }

    function addRegion(opts) {
      if (regionsPlugin && typeof regionsPlugin.addRegion === "function") {
        return regionsPlugin.addRegion(opts);
      }
      if (typeof ws.addRegion === "function") {
        return ws.addRegion(opts);
      }
      return null;
    }

    function seekToSeconds(t) {
      var dur = Number(ws.getDuration() || 0);
      if (typeof ws.setTime === "function") {
        ws.setTime(t);
      } else if (dur > 0 && typeof ws.seekTo === "function") {
        ws.seekTo(Math.min(1, Math.max(0, t / dur)));
      }
    }

    function wireLoopRegion(region) {
      if (!region || typeof region.on !== "function") return;
      var span = Number(region.end) - Number(region.start);
      if (span < 0.12) {
        return;
      }
      loopRegion = region;
      try {
        if (typeof region.setOptions === "function") {
          region.setOptions({ color: "rgba(61, 154, 122, 0.38)" });
        }
      } catch (_e3) {}
      try {
        region.on("in", function () {
          try {
            seekToSeconds(region.start);
            ws.play();
          } catch (_e4) {}
        });
      } catch (_e4b) {}
    }

    function onRegionCreated(region) {
      wireLoopRegion(region);
    }

    if (regionsPlugin && typeof regionsPlugin.on === "function") {
      regionsPlugin.on("region-created", onRegionCreated);
    } else if (typeof ws.on === "function") {
      ws.on("region-created", onRegionCreated);
    }

    function play(id, btn, opts) {
      opts = opts || {};
      lastPlayOpts = cloneOpts(opts);
      var projectId = opts.projectId;
      trackUsage(id, "play", projectId);

      var sid = Number(id);
      var sameTrack = currentPlayingId !== null && Number(currentPlayingId) === sid;

      if (sameTrack) {
        if (ws.isPlaying()) {
          ws.pause();
          setPlayBtnState(currentPlayBtn || btn, false);
        } else {
          ws.play();
          setPlayBtnState(currentPlayBtn || btn, true);
        }
        setActiveRow(sid);
        setPlayingGlow(ws.isPlaying());
        syncDockToggle();
        syncActiveRowProgress();
        return;
      }

      if (currentPlayingId !== null && Number(currentPlayingId) !== sid) {
        try {
          if (typeof ws.stop === "function") {
            ws.stop();
          } else {
            ws.pause();
            seekToSeconds(0);
          }
        } catch (_e5) {}
      }

      if (currentPlayBtn && currentPlayBtn !== btn) {
        setPlayBtnState(currentPlayBtn, false);
      }

      currentPlayingId = sid;
      currentPlayBtn = btn || null;
      pendingPlayBtn = btn || null;

      if (opts.fileList && opts.fileList.length) {
        setFileList(opts.fileList);
      } else if (btn) {
        refreshFileListAroundButton(btn);
      } else if (document.querySelector(".project-audio-files")) {
        syncProjectAudioFileListFromDom();
      }

      currentIndex = fileList.indexOf(sid);

      resetAllListPlayButtons();

      resetAllInlineProgress();
      setActiveRow(sid);
      setPlayingGlow(false);

      if (dock) {
        dock.hidden = false;
      }

      ws.load("/audio/" + sid);
    }

    function togglePlay() {
      ws.playPause();
      if (currentPlayBtn) {
        setPlayBtnState(currentPlayBtn, ws.isPlaying());
      }
      if (currentPlayingId != null) {
        setActiveRow(currentPlayingId);
        setPlayingGlow(ws.isPlaying());
      }
      syncDockToggle();
      syncActiveRowProgress();
    }

    function nextFile() {
      if (!fileList.length || currentIndex < 0 || currentIndex >= fileList.length - 1) return;
      var nid = fileList[currentIndex + 1];
      play(nid, findPlayButtonForFileId(nid), lastPlayOpts);
    }

    function prevFile() {
      if (!fileList.length || currentIndex <= 0) return;
      var pid = fileList[currentIndex - 1];
      play(pid, findPlayButtonForFileId(pid), lastPlayOpts);
    }

    document.addEventListener(
      "keydown",
      function (e) {
        if (isTypingContext()) return;
        if (!ws) return;

        switch (e.code) {
          case "Space":
            e.preventDefault();
            ws.playPause();
            if (currentPlayBtn) setPlayBtnState(currentPlayBtn, ws.isPlaying());
            if (currentPlayingId != null) {
              setActiveRow(currentPlayingId);
              setPlayingGlow(ws.isPlaying());
            }
            syncDockToggle();
            syncActiveRowProgress();
            break;
          case "ArrowRight": {
            e.preventDefault();
            var cur = ws.getCurrentTime();
            var dur = Number(ws.getDuration() || 0);
            var target = cur + 10;
            if (dur > 0) target = Math.min(target, dur);
            seekToSeconds(target);
            syncActiveRowProgress();
            break;
          }
          case "ArrowLeft":
            e.preventDefault();
            seekToSeconds(Math.max(ws.getCurrentTime() - 10, 0));
            syncActiveRowProgress();
            break;
          case "ArrowDown":
            e.preventDefault();
            nextFile();
            break;
          case "ArrowUp":
            e.preventDefault();
            prevFile();
            break;
          default:
            return;
        }
      }
    );

    ws.on("ready", function () {
      ws.play();
      if (pendingPlayBtn) {
        setPlayBtnState(pendingPlayBtn, true);
        currentPlayBtn = pendingPlayBtn;
        pendingPlayBtn = null;
      } else if (currentPlayBtn) {
        setPlayBtnState(currentPlayBtn, true);
      }
      setPlayingGlow(true);
      syncDockToggle();
      syncActiveRowProgress();
    });

    ws.on("play", function () {
      if (currentPlayBtn) setPlayBtnState(currentPlayBtn, true);
      setPlayingGlow(true);
      syncDockToggle();
      syncActiveRowProgress();
    });

    ws.on("pause", function () {
      if (currentPlayBtn) setPlayBtnState(currentPlayBtn, false);
      setPlayingGlow(false);
      syncDockToggle();
      syncActiveRowProgress();
    });

    ws.on("finish", function () {
      if (currentPlayBtn) setPlayBtnState(currentPlayBtn, false);
      setPlayingGlow(false);
      clearActiveRows();
      resetAllInlineProgress();
      currentPlayingId = null;
      currentPlayBtn = null;
      updateDockTrackTitle(null);
      syncDockToggle();
    });

    ws.on("audioprocess", function () {
      syncActiveRowProgress();
      if (timeEl) {
        timeEl.textContent = ws.getCurrentTime().toFixed(1) + "s";
      }
      if (!loopRegion || !ws.isPlaying()) return;
      var t = ws.getCurrentTime();
      var span = Number(loopRegion.end) - Number(loopRegion.start);
      if (span < 0.12) return;
      if (t >= loopRegion.end - 0.04) {
        seekToSeconds(loopRegion.start);
      }
    });

    ws.on("seek", function () {
      if (timeEl) {
        timeEl.textContent = ws.getCurrentTime().toFixed(1) + "s";
      }
      syncActiveRowProgress();
    });

    ws.on("click", function (pos) {
      var duration = Number(ws.getDuration() || 0);
      if (!duration) return;
      var t = duration * Number(pos || 0);
      addRegion({
        start: t,
        end: t + 0.01,
        color: "rgba(255, 0, 0, 0.65)",
      });
    });

    if (container) {
      container.addEventListener(
        "wheel",
        function (e) {
          if (!ws) return;
          e.preventDefault();
          if (e.deltaY < 0) waveformZoomPxPerSec += 20;
          else waveformZoomPxPerSec = Math.max(20, waveformZoomPxPerSec - 20);
          ws.zoom(waveformZoomPxPerSec);
        },
        { passive: false }
      );
    }

    if (toggleBtn) {
      toggleBtn.addEventListener("click", function () {
        togglePlay();
      });
    }

    function notifyRowRemovedFromDom(fileId) {
      if (currentPlayingId == null) return;
      if (Number(fileId) !== Number(currentPlayingId)) return;
      setPlayingGlow(false);
      clearActiveRows();
      resetAllInlineProgress();
    }

    window.TMGlobalAudio = {
      play: play,
      togglePlay: togglePlay,
      setFileList: setFileList,
      syncProjectAudioFileListFromDom: syncProjectAudioFileListFromDom,
      syncMusicLibraryFileListFromDom: syncMusicLibraryFileListFromDom,
      notifyRowRemovedFromDom: notifyRowRemovedFromDom,
      getCurrentPlayingId: function () {
        return currentPlayingId;
      },
      getWaveSurfer: function () {
        return ws;
      },
      getFileList: function () {
        return fileList.slice();
      },
      getCurrentIndex: function () {
        return currentIndex;
      },
    };

    window.togglePlay = togglePlay;
  });
})();
