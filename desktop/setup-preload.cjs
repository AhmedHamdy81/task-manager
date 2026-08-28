"use strict";
const{contextBridge,ipcRenderer}=require("electron");
contextBridge.exposeInMainWorld("bigbangSetup",{getServer:()=>ipcRenderer.invoke("setup:get"),saveServer:u=>ipcRenderer.invoke("setup:save",u),retry:()=>ipcRenderer.invoke("offline:retry"),changeServer:()=>ipcRenderer.invoke("offline:change")});
