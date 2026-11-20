/**
 * Preload script — runs in an isolated context before the renderer loads.
 * Exposes only read-only runtime configuration via contextBridge so
 * contextIsolation and sandbox remain strictly enforced.
 */

const { contextBridge } = require("electron");

const backendPortArg = process.argv.find((arg) => arg.startsWith("--backend-port="));
const backendPort = backendPortArg ? backendPortArg.split("=")[1] : "8000";

contextBridge.exposeInMainWorld(
  "corvusDesktop",
  Object.freeze({
    isDesktop: true,
    platform: process.platform,
    backendUrl: `http://127.0.0.1:${backendPort}`,
  })
);