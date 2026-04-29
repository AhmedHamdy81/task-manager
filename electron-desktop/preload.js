"use strict";

const { contextBridge, ipcRenderer, webUtils } = require("electron");

contextBridge.exposeInMainWorld("taskManagerDesktop", {
  /** @returns {Promise<string[]>} */
  selectFolder: () => ipcRenderer.invoke("desktop:select-folder"),

  /** @returns {Promise<{ name: string, isDirectory: boolean, path: string }[]>} */
  readDirectory: (dirPath) => ipcRenderer.invoke("desktop:read-directory", dirPath),

  /** @returns {Promise<{ exists: boolean, isDirectory: boolean, isFile: boolean, path?: string }>} */
  statPath: (p) => ipcRenderer.invoke("desktop:stat-path", p),

  /**
   * Real filesystem path for a File from a drag/drop event (Electron only).
   * @param {File} file
   * @returns {string}
   */
  getPathForFile: (file) => webUtils.getPathForFile(file),

  /**
   * Copy a file into the Premiere watch folder (if ELECTRON_PREMIERE_WATCH_FOLDER is set).
   * @param {string} filePath
   * @returns {Promise<{ ok: boolean, error?: string, dest?: string }>}
   */
  sendToPremiere: (filePath) => ipcRenderer.invoke("desktop:send-to-premiere", filePath),

  platform: process.platform,
});
