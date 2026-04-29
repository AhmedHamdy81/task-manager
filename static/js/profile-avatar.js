/**
 * Profile avatar: open modal, camera capture or file upload → POST action=avatar_upload.
 */
(function () {
  "use strict";

  var modal = document.getElementById("avatar-modal");
  var openBtn = document.getElementById("avatar-click");
  var closeBtn = document.getElementById("close-avatar-modal");
  var cameraBtn = document.getElementById("avatar-camera-btn");
  var uploadBtn = document.getElementById("avatar-upload-btn");
  var fileInput = document.getElementById("avatar-file-input");
  var cameraWrap = document.getElementById("camera-wrap");
  var video = document.getElementById("camera-video");
  var captureBtn = document.getElementById("capture-btn");
  var canvas = document.getElementById("camera-canvas");
  var errEl = document.getElementById("avatar-modal-error");

  var stream = null;
  var profileUrl = (modal && modal.getAttribute("data-profile-url")) || "/profile";

  function showError(msg) {
    if (!errEl) return;
    if (msg) {
      errEl.textContent = msg;
      errEl.hidden = false;
    } else {
      errEl.textContent = "";
      errEl.hidden = true;
    }
  }

  function stopCamera() {
    if (stream) {
      stream.getTracks().forEach(function (t) {
        t.stop();
      });
      stream = null;
    }
    if (video) {
      video.srcObject = null;
    }
    if (cameraWrap) {
      cameraWrap.hidden = true;
    }
  }

  function closeModal() {
    if (!modal) return;
    stopCamera();
    showError("");
    modal.hidden = true;
    if (openBtn) {
      openBtn.setAttribute("aria-expanded", "false");
    }
    if (fileInput) {
      fileInput.value = "";
    }
  }

  function openModal() {
    if (!modal) return;
    stopCamera();
    showError("");
    modal.hidden = false;
    if (openBtn) {
      openBtn.setAttribute("aria-expanded", "true");
    }
  }

  function postAvatarFile(file) {
    if (!file || !file.size) {
      showError("Choose an image file.");
      return;
    }
    var fd = new FormData();
    fd.append("action", "avatar_upload");
    fd.append("avatar_file", file);
    showError("");
    fetch(profileUrl, {
      method: "POST",
      body: fd,
      credentials: "same-origin",
      headers: { Accept: "text/html,application/xhtml+xml" },
    })
      .then(function (r) {
        if (!r.ok) {
          throw new Error("Upload failed");
        }
        window.location.reload();
      })
      .catch(function () {
        showError("Could not upload photo. Check size (max 2 MB) and format.");
      });
  }

  if (!modal || !openBtn) return;

  openBtn.addEventListener("click", function () {
    openModal();
  });

  if (closeBtn) {
    closeBtn.addEventListener("click", closeModal);
  }

  modal.addEventListener("click", function (e) {
    if (e.target === modal) {
      closeModal();
    }
  });

  if (uploadBtn && fileInput) {
    uploadBtn.addEventListener("click", function () {
      fileInput.click();
    });
  }

  if (fileInput) {
    fileInput.addEventListener("change", function (e) {
      var f = e.target && e.target.files && e.target.files[0];
      if (!f) return;
      postAvatarFile(f);
    });
  }

  if (cameraBtn && video && cameraWrap && captureBtn && canvas) {
    cameraBtn.addEventListener("click", function () {
      showError("");
      stopCamera();
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        showError("Camera is not available in this browser.");
        return;
      }
      var constraints = { video: { facingMode: "user" }, audio: false };
      navigator.mediaDevices
        .getUserMedia(constraints)
        .catch(function () {
          return navigator.mediaDevices.getUserMedia({ video: true, audio: false });
        })
        .then(function (s) {
          stream = s;
          video.srcObject = s;
          cameraWrap.hidden = false;
        })
        .catch(function () {
          showError("Could not access the camera. Check permissions.");
        });
    });

    captureBtn.addEventListener("click", function () {
      if (!video.videoWidth || !video.videoHeight) {
        showError("Wait for the camera preview, then capture.");
        return;
      }
      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
      var ctx = canvas.getContext("2d");
      if (!ctx) {
        showError("Could not capture image.");
        return;
      }
      ctx.drawImage(video, 0, 0);
      canvas.toBlob(
        function (blob) {
          if (!blob) {
            showError("Could not capture image.");
            return;
          }
          var file = new File([blob], "avatar.jpg", { type: "image/jpeg" });
          stopCamera();
          postAvatarFile(file);
        },
        "image/jpeg",
        0.92
      );
    });
  }
})();
