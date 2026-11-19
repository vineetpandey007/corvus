# Desktop Application (Electron + bundled backend)

A self-contained Windows/macOS/Linux desktop app: the Python/FastAPI
backend runs bundled inside the installed app (no separate Python install
needed by the end user), spawned automatically by an Electron shell that
also loads the React dashboard.

**Status:** the full pipeline — Electron spawning the PyInstaller-built
backend, waiting for it to become healthy, and loading the React
dashboard — has been built and verified end-to-end (screenshots and log
output confirming a working login screen, in a headless Linux test
environment). The Windows `.exe` installer itself has **not** been built
or run on real Windows, since PyInstaller and electron-builder don't
cross-compile — you need to run the build on the target OS. See
`docs/TESTING_NOTES.md` in the project root for the full, specific
verification log.

## How it fits together

```
installer (.exe / .dmg / .AppImage)
└── Electron shell (main.js)
     ├── spawns → bundled backend executable (PyInstaller build of
     │             desktop/backend_entry.py + the whole src/ package)
     │             on first launch: auto-generates JWT_SECRET_KEY and
     │             ENCRYPTION_KEY into the OS's per-user app-data folder,
     │             and puts the SQLite DB there too
     └── loads   → built React dashboard (frontend/dist/index.html),
                   which talks to the backend over plain HTTP on
                   127.0.0.1:8000, exactly like the web deployment does
```

Nothing about the backend or frontend code is desktop-specific — the same
`src/` package and the same React app power the web deployment (`docker
compose up`) and this desktop build. `desktop/backend_entry.py` is a thin
wrapper that bootstraps secrets before importing `src.api.main`; see its
docstring and `docs/MODULE_REFERENCE.md` §9 for the exact mechanism.

## Prerequisites

- Node.js 18+
- Python 3.10+ with the project's `requirements.txt` installed, **plus**
  `pyinstaller` (`pip install pyinstaller`)
- The spaCy model downloaded: `python -m spacy download en_core_web_sm`

## Build Steps

All commands from `desktop/`:

```bash
npm install
```

### 1. Build the bundled backend executable

```bash
npm run build:backend
```

Runs PyInstaller against `desktop/backend.spec`, output to
`desktop/dist/dwta-backend/`. This step must run **on the target OS** —
a Linux build produces a Linux binary, run it again on Windows for the
`.exe`, on macOS for the Mach-O binary. Takes a few minutes; the output
directory is large (400-500MB, mostly spaCy's model data and scikit-
learn/scipy) — this is normal for a bundled ML-dependent Python app.

If you add a new third-party import to `src/`, check whether it needs
adding to `desktop/backend.spec`'s `hiddenimports` — PyInstaller's static
analysis follows normal `import` statements automatically, but dynamic/
conditional imports (like uvicorn's event-loop auto-selection) need to be
listed explicitly, or the frozen binary fails at startup rather than at
build time.

### 2. Build the frontend

```bash
npm run build:frontend
```

Runs `npm install && npm run build` inside `../frontend`, output to
`frontend/dist/`.

### 3. Try it unpackaged first

```bash
npm start
```

Runs Electron directly against the just-built backend/frontend, without
going through electron-builder — the fastest way to check everything
works before spending time on a full installer build.

### 4. Build the installer

```bash
npm run dist:win      # Windows .exe (NSIS installer) — run this ON Windows
npm run dist:mac      # macOS .dmg — run this ON macOS
npm run dist:linux    # Linux .AppImage
```

Each of these runs steps 1+2 again automatically, then `electron-builder`
for that platform. Output lands in `desktop/release/`.

## Icons

`desktop/icons/icon.png` and `icon.ico` are **placeholders** (a simple
generated mark, not real branding) — swap them out before a public
release. `icon.icns` (required for the macOS build) isn't included since
it has to be generated with Apple's own `iconutil` on macOS:

```bash
# On macOS, from a 1024x1024 icon.png:
mkdir icon.iconset
sips -z 16 16     icon.png --out icon.iconset/icon_16x16.png
sips -z 32 32     icon.png --out icon.iconset/icon_16x16@2x.png
sips -z 32 32     icon.png --out icon.iconset/icon_32x32.png
sips -z 64 64     icon.png --out icon.iconset/icon_32x32@2x.png
sips -z 128 128   icon.png --out icon.iconset/icon_128x128.png
sips -z 256 256   icon.png --out icon.iconset/icon_128x128@2x.png
sips -z 256 256   icon.png --out icon.iconset/icon_256x256.png
sips -z 512 512   icon.png --out icon.iconset/icon_256x256@2x.png
sips -z 512 512   icon.png --out icon.iconset/icon_512x512.png
cp icon.png icon.iconset/icon_512x512@2x.png
iconutil -c icns icon.iconset -o icons/icon.icns
```

## Known limitations / next steps

- **Windows `.exe` not yet built or run on real Windows.** The spec/config
  are correct and the exact same mechanism was verified working on Linux,
  but "should work identically on Windows" isn't the same claim as
  "confirmed working on Windows" — build and smoke-test it yourself before
  relying on it for a live demo.
- **`python-gnupg` (used for PGP key fingerprinting) shells out to a real
  `gpg` binary** that PyInstaller does not bundle automatically — it must
  already be installed on the machine running the built app. On Windows,
  bundle [Gpg4win](https://www.gpg4win.org/)'s `gpg.exe` alongside the app
  (add it to `extraResources` in `desktop/package.json`) or document it as
  an install prerequisite; this hasn't been done yet.
- **No auto-update mechanism.** `electron-builder` supports one
  (electron-updater + a release feed) but it isn't wired up here.
- **No code signing.** An unsigned Windows `.exe` will trigger a
  SmartScreen warning, and an unsigned macOS `.dmg` will be blocked by
  Gatekeeper by default — both need a real certificate before
  distributing outside your own team.
- **Bundle size (~450MB installed).** Mostly spaCy + scikit-learn/scipy.
  `matplotlib`/`pandas`/`plotly` were already found to be unused and
  excluded (see `docs/MODULE_REFERENCE.md`'s config/dependency notes) —
  further reduction would mean replacing spaCy with a lighter tokenizer,
  which is a real trade-off against stylometry feature quality, not a
  free win.
