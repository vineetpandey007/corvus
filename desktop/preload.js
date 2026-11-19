/**
 * Preload script — runs in an isolated context before the renderer loads.
 *
 * Currently exposes nothing: the React dashboard talks to the backend
 * over plain HTTP (via axios, see frontend/src/api/client.js), not
 * through Electron IPC, so there's no privileged API surface the
 * renderer needs. This file exists so contextIsolation can stay enabled
 * (Electron security best practice) rather than being skipped.
 *
 * If a future feature needs real OS integration (native file save
 * dialogs, system notifications, etc.), expose it here explicitly via
 * contextBridge.exposeInMainWorld — never re-enable nodeIntegration in
 * the renderer as a shortcut.
 */

// Intentionally empty for now.
