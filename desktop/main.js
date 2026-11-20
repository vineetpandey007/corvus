/**
 * Electron main process — hardened desktop shell for Corvus.
 *
 * Security & reliability invariants:
 *   1. Single-instance lock (prevents concurrent SQLite lock contention).
 *   2. Ephemeral 127.0.0.1 port allocation (eliminates port 8000 collisions).
 *   3. Full process-tree cleanup on exit (prevents Windows PyInstaller orphans).
 *   4. Strict navigation & window-open lockdown (contextIsolation + sandbox).
 */

const { app, BrowserWindow, dialog, shell } = require("electron");
const path = require("path");
const fs = require("fs");
const http = require("http");
const net = require("net");
const { spawn, execFileSync } = require("child_process");

const isDev = !app.isPackaged;
const BACKEND_HOST = "127.0.0.1";
const STARTUP_TIMEOUT_MS = 45000;

let backendProcess = null;
let backendLogStream = null;
let resolvedBackendPort = null;
let mainWindow = null;
let splashWindow = null;

// Prevent multiple instances from fighting over the local SQLite database
const gotSingleInstanceLock = app.requestSingleInstanceLock();
if (!gotSingleInstanceLock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }
  });
}

function findAvailablePort(preferredPort) {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.on("error", () => {
      // Preferred port is occupied; fall back to OS-assigned ephemeral port
      const fallback = net.createServer();
      fallback.unref();
      fallback.on("error", reject);
      fallback.listen(0, BACKEND_HOST, () => {
        const { port } = fallback.address();
        fallback.close(() => resolve(String(port)));
      });
    });
    server.listen(Number(preferredPort) || 0, BACKEND_HOST, () => {
      const { port } = server.address();
      server.close(() => resolve(String(port)));
    });
  });
}

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

function waitForBackendHealth(port, timeoutMs) {
  const startedAt = Date.now();
  const healthUrl = `http://${BACKEND_HOST}:${port}/health`;

  return new Promise((resolve, reject) => {
    const attempt = () => {
      const req = http.get(healthUrl, { timeout: 2000 }, (res) => {
        res.resume();
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

function startBackend(port) {
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
  const logPath = path.join(appDataDir, "backend-process.log");
  backendLogStream = fs.createWriteStream(logPath, { flags: "a" });

  backendProcess = spawn(exePath, [], {
    env: {
      ...process.env,
      APP_DATA_DIR: appDataDir,
      HOST: BACKEND_HOST,
      PORT: port,
    },
    stdio: ["ignore", "pipe", "pipe"],
  });

  backendProcess.stdout.pipe(backendLogStream);
  backendProcess.stderr.pipe(backendLogStream);
  if (isDev) {
    backendProcess.stdout.pipe(process.stdout);
    backendProcess.stderr.pipe(process.stderr);
  }

  backendProcess.on("error", (err) => {
    dialog.showErrorBox("Corvus Backend Error", String(err));
  });

  backendProcess.on("exit", (code, signal) => {
    if (code !== 0 && code !== null) {
      console.error(`Backend process exited unexpectedly (code=${code}, signal=${signal})`);
    }
    backendProcess = null;
  });
}

function stopBackend() {
  if (!backendProcess || !backendProcess.pid) return;
  const pid = backendProcess.pid;
  try {
    if (process.platform === "win32") {
      // Terminate PyInstaller bootloader + child uvicorn worker tree cleanly
      execFileSync("taskkill", ["/pid", String(pid), "/T", "/F"], { stdio: "ignore" });
    } else {
      backendProcess.kill("SIGTERM");
    }
  } catch {
    // Process already exited
  } finally {
    backendProcess = null;
    if (backendLogStream) {
      backendLogStream.end();
      backendLogStream = null;
    }
  }
}

function createSplashWindow() {
  splashWindow = new BrowserWindow({
    width: 420,
    height: 320,
    frame: false,
    resizable: false,
    center: true,
    backgroundColor: "#0f1115",
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  splashWindow.loadFile(path.join(__dirname, "splash.html"));
}

function createMainWindow(port) {
  const indexPath = getFrontendIndexPath();

  mainWindow = new BrowserWindow({
    width: 1320,
    height: 860,
    minWidth: 900,
    minHeight: 600,
    backgroundColor: "#0f1115",
    icon: path.join(__dirname, "icons", "icon.png"),
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      additionalArguments: [`--backend-port=${port}`],
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  // Prevent untrusted links inside ingested posts from navigating the Electron shell
  mainWindow.webContents.on("will-navigate", (event, targetUrl) => {
    if (!targetUrl.startsWith("file://")) {
      event.preventDefault();
    }
  });

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith("https://") || url.startsWith("http://")) {
      shell.openExternal(url);
    }
    return { action: "deny" };
  });

  mainWindow.loadFile(indexPath);
  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

async function boot() {
  if (!gotSingleInstanceLock) return;
  createSplashWindow();

  try {
    const preferredPort =
      process.env.CORVUS_BACKEND_PORT || process.env.DWTA_BACKEND_PORT || "8000";
    resolvedBackendPort = await findAvailablePort(preferredPort);
    startBackend(resolvedBackendPort);
    await waitForBackendHealth(resolvedBackendPort, STARTUP_TIMEOUT_MS);
  } catch (err) {
    stopBackend();
    if (splashWindow) splashWindow.close();
    dialog.showErrorBox(
      "Corvus Startup Failed",
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
  createMainWindow(resolvedBackendPort);
}

app.whenReady().then(boot);

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("before-quit", () => {
  stopBackend();
});

app.on("activate", () => {
  if (BrowserWindow.getAllWindows().length === 0 && resolvedBackendPort) {
    createMainWindow(resolvedBackendPort);
  }
});