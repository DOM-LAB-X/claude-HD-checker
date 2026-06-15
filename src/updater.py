"""Auto-update checker for HD Clearance Tracker.

Checks the GitHub Releases API for a newer version. When one is found,
downloads the release zip, extracts it to a temp directory, writes a bat
script that replaces the current install and relaunches the app.

Only active when running as a frozen PyInstaller exe (sys.frozen == True).
"""
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from threading import Thread

from src.logging_setup import get_logger

log = get_logger()

GITHUB_REPO = "DOM-LAB-X/claude-HD-checker"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASE_ASSET_NAME = "HD-Tracker.zip"

_update_info: dict | None = None


def _parse_version(v: str) -> tuple:
    try:
        return tuple(int(x) for x in v.lstrip("v").split("."))
    except ValueError:
        return (0,)


def get_local_version() -> str:
    from src.config import BUNDLE_DIR
    p = BUNDLE_DIR / "version.txt"
    return p.read_text().strip() if p.exists() else "0.0.0"


def get_pending_update() -> dict | None:
    return _update_info


def check_for_update() -> dict | None:
    """Return {"version": "v1.x.x", "download_url": "..."} if newer release exists."""
    global _update_info
    try:
        req = urllib.request.Request(
            GITHUB_API_URL,
            headers={"Accept": "application/vnd.github+json", "User-Agent": "HD-Tracker"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())

        tag = data.get("tag_name", "")
        assets = data.get("assets", [])
        download_url = next(
            (a["browser_download_url"] for a in assets if a["name"] == RELEASE_ASSET_NAME),
            None,
        )

        if _parse_version(tag) > _parse_version(get_local_version()) and download_url:
            _update_info = {"version": tag, "download_url": download_url}
            return _update_info
    except Exception:
        log.exception("Update check failed")
    return None


def start_background_check(on_update_found):
    """Spawn a daemon thread to check for updates.

    Calls on_update_found(version_str) on the background thread if a newer
    release is available. No-op when not running as a packaged exe.
    """
    if not getattr(sys, "frozen", False):
        return

    def _check():
        info = check_for_update()
        if info:
            on_update_found(info["version"])

    Thread(target=_check, daemon=True).start()


def apply_update(on_progress=None) -> None:
    """Download the release zip and hand off to an external updater bat.

    Raises on failure. The caller should quit the app after this returns so
    the updater bat can replace the exe files without them being locked.
    """
    if not _update_info:
        raise RuntimeError("No pending update.")

    install_dir = Path(sys.executable).resolve().parent
    tmp_dir = Path(tempfile.mkdtemp(prefix="hd-tracker-upd-"))

    try:
        zip_path = tmp_dir / "update.zip"
        if on_progress:
            on_progress("Downloading update...")
        urllib.request.urlretrieve(_update_info["download_url"], zip_path)

        if on_progress:
            on_progress("Extracting update...")
        extract_dir = tmp_dir / "x"
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(extract_dir)

        # Release zip should contain an HD-Tracker/ subdirectory.
        new_files = extract_dir / "HD-Tracker"
        if not new_files.exists():
            new_files = extract_dir  # fallback: files are at zip root

        # Write the updater bat next to the exe.  It waits for the app to
        # exit, copies new files over (preserving user data), relaunches,
        # then deletes itself and the temp dir.
        updater_bat = install_dir / "_updater.bat"
        updater_bat.write_text(
            "@echo off\r\n"
            "timeout /t 3 /nobreak >nul\r\n"
            f'robocopy "{new_files}" "{install_dir}" /E /IS /IT /NFL /NDL /NJH /NJS'
            " /XD data /XF config.yaml /XF watchlist.txt\r\n"
            f'rd /s /q "{tmp_dir}"\r\n'
            f'start "" "{install_dir / "HD-Tracker.exe"}"\r\n'
            'del "%~f0"\r\n',
            encoding="utf-8",
        )

        no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.Popen(
            ["cmd.exe", "/c", str(updater_bat)],
            creationflags=no_window,
        )

    except Exception:
        log.exception("Failed to apply update")
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise
