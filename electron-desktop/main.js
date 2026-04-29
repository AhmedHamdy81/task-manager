"use strict";

const { app, BrowserWindow, dialog, ipcMain } = require("electron");
const path = require("path");
const fs = require("fs");
const fsp = require("fs/promises");
const { spawn } = require("child_process");
const http = require("http");

/** Parent of electron-desktop/ — repo root containing app.py */
const BACKEND_ROOT = path.join(__dirname, "..");
const HOST = process.env.HOST || "127.0.0.1";
const PORT = String(process.env.PORT || "5001");
const START_URL = `http://${HOST}:${PORT}/`;

let flaskProcess = null;
let mainWindow = null;
let appIsQuitting = false;

function pythonExecutable() {
  return process.env.FLASK_PYTHON || (process.platform === "win32" ? "python" : "python3");
}

function startFlask() {
  const script = path.join(BACKEND_ROOT, "app.py");
  if (!fs.existsSync(script)) {
    dialog.showErrorBox(
      "Backend not found",
      `Expected app.py at:\n${script}\n\nOpen the desktop app from the task-manager repository (electron-desktop inside the project).`
    );
    app.quit();
    return;
  }

  const env = {
    ...process.env,
    HOST,
    PORT,
    PYTHONUNBUFFERED: "1",
  };

  flaskProcess = spawn(pythonExecutable(), [script], {
    cwd: BACKEND_ROOT,
    env,
    stdio: ["ignore", "pipe", "pipe"],
  });

  flaskProcess.stdout.on("data", (d) => process.stdout.write(d));
  flaskProcess.stderr.on("data", (d) => process.stderr.write(d));
  flaskProcess.on("error", (err) => {
    dialog.showErrorBox("Flask failed to start", String(err && err.message ? err.message : err));
  });
  flaskProcess.on("exit", (code, signal) => {
    if (code !== null && code !== 0 && !appIsQuitting) {
      dialog.showErrorBox(
        "Flask exited",
        `The server process ended (code ${code}). Check the terminal log or Python environment.`
      );
    }
  });
}

function waitForHttpOk(url, timeoutMs = 90000) {
  return new Promise((resolve, reject) => {
    const deadline = Date.now() + timeoutMs;
    function ping() {
      const req = http.get(url, { timeout: 2500 }, (res) => {
        res.resume();
        resolve();
      });
      req.on("error", () => {
        if (Date.now() > deadline) {
          reject(new Error(`Timed out waiting for ${url}`));
        } else {
          setTimeout(ping, 350);
        }
      });
      req.on("timeout", () => {
        req.destroy();
        if (Date.now() > deadline) {
          reject(new Error(`Timed out waiting for ${url}`));
        } else {
          setTimeout(ping, 350);
        }
      });
    }
    ping();
  });
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 840,
    minWidth: 900,
    minHeight: 600,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });

  mainWindow.loadURL(START_URL);
  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

app.on("ready", async () => {
  ipcMain.handle("desktop:select-folder", async () => {
    const win = BrowserWindow.getFocusedWindow() || mainWindow;
    const { canceled, filePaths } = await dialog.showOpenDialog(win, {
      properties: ["openDirectory", "createDirectory"],
    });
    if (canceled || !filePaths || !filePaths.length) return [];
    return filePaths;
  });

  ipcMain.handle("desktop:stat-path", async (_evt, p) => {
    const raw = String(p || "").trim();
    if (!raw) return { exists: false, isDirectory: false, isFile: false };
    const resolved = path.resolve(raw);
    try {
      const st = await fsp.stat(resolved);
      return {
        exists: true,
        path: resolved,
        isDirectory: st.isDirectory(),
        isFile: st.isFile(),
      };
    } catch {
      return { exists: false, isDirectory: false, isFile: false, path: resolved };
    }
  });

  ipcMain.handle("desktop:read-directory", async (_evt, dirPath) => {
    const raw = String(dirPath || "").trim();
    if (!raw) return [];
    const resolved = path.resolve(raw);
    if (!resolved || !fs.existsSync(resolved) || !fs.statSync(resolved).isDirectory()) {
      return [];
    }
    const entries = await fsp.readdir(resolved, { withFileTypes: true });
    return entries.map((ent) => ({
      name: ent.name,
      isDirectory: ent.isDirectory(),
      path: path.join(resolved, ent.name),
    }));
  });

  ipcMain.handle("desktop:send-to-premiere", async (_evt, filePath) => {
    const watch = process.env.ELECTRON_PREMIERE_WATCH_FOLDER || process.env.PREMIERE_WATCH_FOLDER;
    if (!watch) {
      return { ok: false, error: "Set ELECTRON_PREMIERE_WATCH_FOLDER to a folder Premiere watches." };
    }
    const src = String(filePath || "").trim();
    if (!src || !fs.existsSync(src) || !fs.statSync(src).isFile()) {
      return { ok: false, error: "Invalid source file." };
    }
    const destDir = path.resolve(watch);
    if (!fs.existsSync(destDir) || !fs.statSync(destDir).isDirectory()) {
      return { ok: false, error: "Watch folder does not exist or is not a directory." };
    }
    const base = path.basename(src);
    const dest = path.join(destDir, base);
    await fsp.copyFile(src, dest);
    return { ok: true, dest };
  });

  startFlask();
  try {
    await waitForHttpOk(START_URL);
  } catch (e) {
    dialog.showErrorBox(
      "Server not reachable",
      `Could not connect to Flask at ${START_URL}\n\n${e && e.message ? e.message : e}`
    );
    app.quit();
    return;
  }
  createWindow();
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

app.on("before-quit", () => {
  appIsQuitting = true;
  if (flaskProcess && !flaskProcess.killed) {
    flaskProcess.kill("SIGTERM");
  }
});

app.on("activate", () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow();
});
