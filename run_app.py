"""
run_app.py — OMNIQA Launcher

This is the entry point for the packaged executable (.exe / .app).
It:
  1. Shows a native folder-picker dialog on first launch (or if the saved
     output folder no longer exists) via Tkinter — before the browser opens.
  2. Persists the chosen folder to ~/.omniqa/config.json.
  3. Sets the OMNIQA_OUTPUT_DIR environment variable so app.py can read it.
  4. Launches the Streamlit server and opens the browser automatically.

During development, just keep using:
    streamlit run app.py
"""

from __future__ import annotations

import json
import os
import sys
import subprocess
from pathlib import Path


# ── Config helpers ────────────────────────────────────────────────────────────

CONFIG_DIR = Path.home() / ".omniqa"
CONFIG_FILE = CONFIG_DIR / "config.json"


def _load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_config(data: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


# ── Output-folder picker ──────────────────────────────────────────────────────

def _pick_output_folder(initial: str | None = None) -> str | None:
    """
    Opens a native OS folder-picker dialog using Tkinter.
    Returns the chosen path string, or None if the user cancels.
    """
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox

        root = tk.Tk()
        root.withdraw()  # hide the blank root window
        root.attributes("-topmost", True)

        messagebox.showinfo(
            "OMNIQA — First Launch Setup",
            "Please choose a folder where OMNIQA will save output reports.\n\n"
            "You can change this later by deleting:\n"
            f"  {CONFIG_FILE}",
            parent=root,
        )

        folder = filedialog.askdirectory(
            title="Choose OMNIQA Output Folder",
            initialdir=initial or str(Path.home()),
            mustexist=False,
            parent=root,
        )
        root.destroy()
        return folder or None
    except Exception as exc:
        print(f"[OMNIQA] Tkinter dialog failed: {exc}. Falling back to ~/OMNIQA-Output.")
        return None


def _resolve_output_dir() -> str:
    """
    Returns a valid output directory path.
    Uses saved config → prompts user if missing / invalid → falls back to default.
    """
    config = _load_config()
    saved = config.get("output_dir")

    if saved and Path(saved).is_dir():
        print(f"[OMNIQA] Using saved output folder: {saved}")
        return saved

    # Need to pick a new folder
    chosen = _pick_output_folder(initial=saved)

    if not chosen:
        # User cancelled or dialog failed — use default
        default = str(Path.home() / "OMNIQA-Output")
        print(f"[OMNIQA] No folder chosen. Defaulting to: {default}")
        chosen = default

    Path(chosen).mkdir(parents=True, exist_ok=True)
    config["output_dir"] = chosen
    _save_config(config)
    print(f"[OMNIQA] Output folder saved: {chosen}")
    return chosen


# ── Resolve paths when frozen (PyInstaller) vs. dev ──────────────────────────

def _get_base_path() -> Path:
    """Returns the directory containing app.py (works frozen and in dev)."""
    if getattr(sys, "frozen", False):
        # PyInstaller extracts to sys._MEIPASS
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).parent.resolve()


# ── Main launcher ─────────────────────────────────────────────────────────────

def main() -> None:
    output_dir = _resolve_output_dir()
    os.environ["OMNIQA_OUTPUT_DIR"] = output_dir

    base_path = _get_base_path()
    app_script = str(base_path / "app.py")
    config_toml = str(base_path / "config.toml")

    # Build the streamlit CLI command.
    # We call the streamlit module directly so it works inside a frozen binary.
    cmd = [
        sys.executable,
        "-m", "streamlit",
        "run",
        app_script,
        "--server.headless", "false",
        "--server.port", "8501",
        "--browser.gatherUsageStats", "false",
        "--global.developmentMode", "false",
        "--server.maxUploadSize", "5120",
        "--server.maxMessageSize", "5120",
        "--server.enableXsrfProtection", "false",
    ]

    print(f"[OMNIQA] Launching: {' '.join(cmd)}")
    try:
        proc = subprocess.Popen(cmd)
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()


if __name__ == "__main__":
    main()
