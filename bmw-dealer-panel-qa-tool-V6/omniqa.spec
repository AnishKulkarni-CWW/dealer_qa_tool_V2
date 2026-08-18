# omniqa.spec
# PyInstaller spec for OMNIQA — Element Presence Checker
#
# Build commands (run from the project root):
#   Mac:     pyinstaller omniqa.spec
#   Windows: pyinstaller omniqa.spec
#
# Outputs:
#   dist/OMNIQA          (Mac .app bundle directory — then wrapped into .dmg by CI)
#   dist/OMNIQA.exe      (Windows single-file executable)

import sys
import os
from pathlib import Path
import streamlit

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT = Path(SPECPATH)  # directory containing this .spec file
STREAMLIT_PATH = Path(streamlit.__file__).parent

# ── Collect all Streamlit data (static assets, frontend, etc.) ────────────────
from PyInstaller.utils.hooks import collect_data_files, collect_all

st_datas, st_binaries, st_hiddenimports = collect_all("streamlit")

# ── Additional data files to bundle ───────────────────────────────────────────
added_datas = [
    # Our app modules
    (str(ROOT / "app.py"),        "."),
    (str(ROOT / "config.toml"),   "."),
    (str(ROOT / ".streamlit"),    ".streamlit"),
    (str(ROOT / "components"),    "components"),
    (str(ROOT / "core"),          "core"),
]
added_datas += st_datas

# ── Hidden imports needed by Streamlit + our dependencies ─────────────────────
hidden_imports = st_hiddenimports + [
    # Streamlit internals
    "streamlit.web.cli",
    "streamlit.runtime.scriptrunner.magic_funcs",
    "streamlit.components.v1",
    "streamlit.elements",
    # Our deps
    "psd_tools",
    "psd_tools.composite",
    "psd_tools.api",
    "PIL",
    "PIL.Image",
    "PIL._imaging",
    "PIL.ImageOps",
    "PIL.ImageDraw",
    "openpyxl",
    "openpyxl.styles",
    "openpyxl.utils",
    "pandas",
    "numpy",
    # Tkinter (for the folder-picker dialog)
    "tkinter",
    "tkinter.filedialog",
    "tkinter.messagebox",
    # stdlib
    "json",
    "logging",
    "pathlib",
    "typing",
    "email.mime.text",
    "email.mime.multipart",
]

# ── Analysis ──────────────────────────────────────────────────────────────────
a = Analysis(
    [str(ROOT / "run_app.py")],
    pathex=[str(ROOT)],
    binaries=st_binaries,
    datas=added_datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["matplotlib", "scipy", "IPython", "pytest", "jupyter"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

# ── Platform-specific executable config ───────────────────────────────────────
IS_WINDOWS = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,          # keep as dir-based build (faster, more reliable)
    name="OMNIQA",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,                  # no terminal window on Windows
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "assets" / "icon.ico") if IS_WINDOWS and (ROOT / "assets" / "icon.ico").exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="OMNIQA",
)

# ── Mac .app bundle ────────────────────────────────────────────────────────────
if IS_MAC:
    app = BUNDLE(
        coll,
        name="OMNIQA.app",
        icon=str(ROOT / "assets" / "icon.icns") if (ROOT / "assets" / "icon.icns").exists() else None,
        bundle_identifier="com.omniqa.design-checker",
        info_plist={
            "CFBundleDisplayName": "OMNIQA",
            "CFBundleShortVersionString": "1.0.0",
            "CFBundleVersion": "1.0.0",
            "NSHighResolutionCapable": True,
            "NSRequiresAquaSystemAppearance": False,
            "LSMinimumSystemVersion": "12.0",
        },
    )
