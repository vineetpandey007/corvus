/**
 * Electron main process.
 *
 * Responsibilities, in order:
 *   1. Show a splash screen immediately (backend cold-start, especially
 *      spaCy's model load, can take a few seconds — an instant window
 *      beats a few seconds of nothing).
 *   2. Spawn the bundled PyInstaller backend executable, pointed at a
 *      per-OS user-data directory via APP_DATA_DIR (see
 *      desktop/backend_entry.py — this is what triggers first-run secret
 *      generation and routes the SQLite DB there instead of into the
 *      installed app's own directory, which may not be writable).
 *   3. Poll /health until the backend responds, then swap the splash
 *      screen for the real app window loading the built React dashboard.
 *   4. On quit, kill the backend child process — it must never be left
 *      running orphaned after the app closes.
 */

const { app, BrowserWindow, dialog } = require("electron");
const path = require("path");
const fs = require("fs");
const http = require("http");
const { spawn } = require("child_process");

const isDev = !app.isPackaged;
const BACKEND_PORT = process.env.DWTA_BACKEND_PORT || "8000";
const BACKEND_HOST = "127.0.0.1";
const HEALTH_URL = `http://${BACKEND_HOST}:${BACKEND_PORT}/health`;
const STARTUP_TIMEOUT_MS = 45000; // generous — first run on a slow disk can be slow to cold-start

let backendProcess = null;
let mainWindow = null;
let splashWindow = null;

function getBackendExecutablePath() {
  const exeName = process.platform === "win32" ? "dwta-backend.exe" : "dwta-backend";
  const dir = isDev
    ? path.join(__dirname, "dist", "dwta-backend")
    : path.join(process.resourcesPath, "backend");
  return path.join(dir, exeName);
}

function getFrontendIndexPath() {
  return isDev
    ? path.join(__dirname, "..", "frontend", "dist", "index.html")
    : path.join(process.resourcesPath, "frontend", "index.html");
}

function waitForBackendHealth(timeoutMs) {
  const startedAt = Date.now();
  return new Promise((resolve, reject) => {
    const attempt = () => {
      const req = http.get(HEALTH_URL, { timeout: 2000 }, (res) => {
        res.resume(); // drain
        if (res.statusCode === 200) {
          resolve();
        } else {
          scheduleRetry();
        }
      });
      req.on("error", scheduleRetry);
      req.on("timeout", () => {
        req.destroy();
        scheduleRetry();
      });
    };
    const scheduleRetry = () => {
      if (Date.now() - startedAt > timeoutMs) {
        reject(new Error(`Backend did not become healthy within ${timeoutMs}ms`));
        return;
      }
      setTimeout(attempt, 500);
    };
    attempt();
  });
}

function startBackend() {
  const exePath = getBackendExecutablePath();

  if (!fs.existsSync(exePath)) {
    throw new Error(
      `Backend executable not found at: ${exePath}\n\n` +
        (isDev
          ? "Run `npm run build:backend` first (see desktop/README.md)."
          : "This packaged build is missing its backend binary — reinstall the application.")
    );
  }

  const appDataDir = app.getPath("userData");

  backendProcess = spawn(exePath, [], {
    env: {
      ...process.env,
      APP_DATA_DIR: appDataDir,
      HOST: BACKEND_HOST,
      PORT: BACKEND_PORT,
    },
    // In dev, pipe the backend's own logs straight to this process's
    // console — invaluable while iterating. In a packaged build, still
    // capture them (rather than discarding) so a support request can ask
    // for the log file below instead of asking the user to run from a
    // terminal.
    stdio: ["ignore", "pipe", "pipe"],
  });

  const logPath = path.join(appDataDir, "backend-process.log");
  const logStream = fs.createWriteStream(logPath, { flags: "a" });
  backendProcess.stdout.pipe(logStream);
  backendProcess.stderr.pipe(logStream);
  if (isDev) {
    backendProcess.stdout.pipe(process.stdout);
    backendProcess.stderr.pipe(process.stderr);
  }

  backendProcess.on("error", (err) => {
    dialog.showErrorBox("Backend failed to start", String(err));
  });

  backendProcess.on("exit", (code, signal) => {
    if (code !== 0 && code !== null) {
      console.error(`Backend process exited unexpectedly (code=${code}, signal=${signal})`);
    }
  });
}

function createSplashWindow() {
  splashWindow = new BrowserWindow({
    width: 420,
    height: 320,
    frame: false,
    resizable: false,
    center: true,
    backgroundColor: "#0f1115",
    webPreferences: { contextIsolation: true },
  });
  splashWindow.loadFile(path.join(__dirname, "splash.html"));
}

function createMainWindow() {
  mainWindow = new BrowserWindow({
    width: 1320,
    height: 860,
    minWidth: 900,
    minHeight: 600,
    backgroundColor: "#0f1115",
    icon: path.join(__dirname, "icons", "icon.png"),
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  mainWindow.loadFile(getFrontendIndexPath());
  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

async function boot() {
  createSplashWindow();

  try {
    startBackend();
    await waitForBackendHealth(STARTUP_TIMEOUT_MS);
  } catch (err) {
    if (splashWindow) splashWindow.close();
    dialog.showErrorBox(
      "Startup failed",
      `The local backend service did not start correctly.\n\n${err.message}\n\n` +
        `Log file: ${path.join(app.getPath("userData"), "backend-process.log")}`
    );
    app.quit();
    return;
  }

  if (splashWindow) {
    splashWindow.close();
    splashWindow = null;
  }
  createMainWindow();
}

app.whenReady().then(boot);

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("before-quit", () => {
  if (backendProcess && !backendProcess.killed) {
    backendProcess.kill();
  }
});

app.on("activate", () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    createMainWindow();
  }
});
