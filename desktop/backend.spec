# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for the bundled desktop backend.

Build with (from the project root):
    pyinstaller desktop/backend.spec --distpath desktop/dist --workpath desktop/build

Output: desktop/dist/dwta-backend/dwta-backend(.exe) — a folder containing
the executable plus its dependencies (--onedir, not --onefile: onedir
starts faster and makes spaCy's data-file bundling far less fragile than
forcing everything through a single-file self-extracting archive).

This spec is OS-agnostic in syntax, but PyInstaller does NOT cross-compile
— running this on Linux produces a Linux binary, on Windows a .exe, on
macOS a Mach-O binary. Build on (or in CI for) each target OS separately.
See desktop/README.md for the full per-OS build instructions.
"""

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

PROJECT_ROOT = Path(SPECPATH).resolve().parent  # SPECPATH = desktop/, so parent = repo root

block_cipher = None

# spaCy and its installed language model both ship non-Python data files
# (vocab tables, lookup data, meta.json, etc.) that PyInstaller's default
# import analysis won't find on its own — collect_all() pulls in every
# submodule, data file, and binary PyInstaller can find for each package.
datas = []
binaries = []
hiddenimports = []

for pkg in ("spacy", "en_core_web_sm", "thinc", "srsly", "blis", "catalogue",
            "preshed", "cymem", "murmurhash", "wasabi"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        # Some of spaCy's transitive deps vary by version/platform — don't
        # let a missing optional one abort the whole build.
        pass

# uvicorn dynamically imports its event-loop and protocol implementations
# based on what's installed, which PyInstaller's static analysis can't see
# — these must be listed explicitly or the frozen binary fails at startup
# with "no module named uvicorn.loops.auto" (or similar) the moment
# uvicorn.run() tries to select an implementation.
hiddenimports += [
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
]

# NOTE: we deliberately do NOT blanket collect_submodules("src") here.
# PyInstaller's normal import-graph analysis (starting from
# backend_entry.py -> src.api.main -> ... ) already correctly follows every
# module actually reachable at runtime, including transitive third-party
# deps like scikit-learn (via stylometry/author_matcher.py). A blanket
# collect_submodules("src") was tried during development and force-included
# unrelated modules never touched by the API process — e.g.
# src.visualization.graph_viz (matplotlib, only used by scripts/run_pipeline.py)
# and src.ingestion.forum_scraper (bs4/lxml, not wired into any API route)
# — nearly doubling the bundle size for code that never runs in the desktop
# backend. If a genuinely dynamic import is ever added that static analysis
# can't see, add its specific module path to hiddenimports below rather
# than reintroducing the blanket collection.

# The bundled app also needs config/config.yaml and the sample dataset
# alongside the executable at runtime (config.py resolves CONFIG_PATH
# relative to the package location, which after freezing is sys._MEIPASS).
datas += [
    (str(PROJECT_ROOT / "config" / "config.yaml"), "config"),
]

a = Analysis(
    [str(PROJECT_ROOT / "desktop" / "backend_entry.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Keep the bundle smaller — none of these are used at runtime by
        # the API process itself. matplotlib in particular is NOT imported
        # by anything the API reaches (only scripts/run_pipeline.py's PNG
        # export uses it) — it gets pulled in as a side effect of
        # scikit-learn's own PyInstaller hook (sklearn.tree has an optional
        # matplotlib integration our code never calls), not by our imports.
        "matplotlib", "pandas", "plotly",
        "matplotlib.tests", "numpy.tests", "pandas.tests",
    ],
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="dwta-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX compression makes some AV engines flag the binary — skip it
    console=True,  # keep a console window on Windows for now, for visible error output during setup
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="dwta-backend",
)
