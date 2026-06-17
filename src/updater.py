"""Auto-update checker for HD Clearance Tracker.

Checks the GitHub Releases API for a newer version. When one is found,
downloads the release zip, extracts it to a temp directory, then launches
a small platform-specific updater script that replaces the running app and
relaunches it.

Only active when running as a frozen PyInstaller bundle (sys.frozen == True).
"""
import json
import os
import platform
import shutil
import ssl
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from threading import Thread

from src.logging_setup import get_logger

log = get_logger()


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


GITHUB_REPO = "DOM-LAB-X/claude-HD-checker"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

# Platform-specific release asset names must match what GitHub Actions uploads.
_ASSET_NAMES = {
    "Darwin": "HD-Tracker-mac.zip",
    "Windows": "HD-Tracker.zip",
}
RELEASE_ASSET_NAME = _ASSET_NAMES.get(platform.system(), "HD-Tracker.zip")

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
    """Return {"version": "v1.x.x", "download_url": "..."} if a newer release exists."""
    global _update_info
    try:
        req = urllib.request.Request(
            GITHUB_API_URL,
            headers={"Accept": "application/vnd.github+json", "User-Agent": "HD-Tracker"},
        )
        with urllib.request.urlopen(req, timeout=15, context=_ssl_context()) as resp:
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

    Calls on_update_found(version_str) if a newer release is available.
    No-op when not running as a packaged exe/app.
    """
    if not getattr(sys, "frozen", False):
        return

    def _check():
        info = check_for_update()
        if info:
            on_update_found(info["version"])

    Thread(target=_check, daemon=True).start()


def _apply_windows(install_dir: Path, tmp_dir: Path, new_files: Path) -> None:
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
    subprocess.Popen(["cmd.exe", "/c", str(updater_bat)], creationflags=no_window)


def _apply_mac(app_bundle: Path, install_dir: Path, tmp_dir: Path, extract_dir: Path) -> None:
    # The zip should contain HD-Tracker.app at its root.
    new_app = extract_dir / "HD-Tracker.app"
    if not new_app.exists():
        new_app = extract_dir  # fallback: zip root is already the .app

    updater_sh = tmp_dir / "_updater.sh"
    updater_sh.write_text(
        "#!/bin/bash\n"
        "sleep 3\n"
        f'rm -rf "{app_bundle}"\n'
        f'cp -rf "{new_app}" "{install_dir}/"\n'
        # Strip Gatekeeper quarantine — without this macOS silently blocks
        # the launch of an app that was copied from a temp directory.
        f'xattr -cr "{install_dir}/HD-Tracker.app" 2>/dev/null || true\n'
        f'open "{install_dir}/HD-Tracker.app"\n'
        f'rm -rf "{tmp_dir}"\n'
        'rm -- "$0"\n',
        encoding="utf-8",
    )
    os.chmod(updater_sh, 0o755)
    subprocess.Popen(["bash", str(updater_sh)])


def apply_update(on_progress=None) -> None:
    """Download the release zip and hand off to a platform updater script.

    Raises on failure. The caller should quit the app after this returns so
    the updater script can replace files without them being locked.
    """
    if not _update_info:
        raise RuntimeError("No pending update.")

    tmp_dir = Path(tempfile.mkdtemp(prefix="hd-tracker-upd-"))

    try:
        zip_path = tmp_dir / "update.zip"
        if on_progress:
            on_progress("Downloading update...")
        dl_req = urllib.request.Request(
            _update_info["download_url"],
            headers={"User-Agent": "HD-Tracker"},
        )
        with urllib.request.urlopen(dl_req, timeout=120, context=_ssl_context()) as resp:
            with open(zip_path, "wb") as f:
                shutil.copyfileobj(resp, f)

        if on_progress:
            on_progress("Extracting update...")
        extract_dir = tmp_dir / "x"
        extract_dir.mkdir()
        with zipfile.ZipFile(zip_path, "r") as z:
            for member in z.infolist():
                member_path = (extract_dir / member.filename).resolve()
                if not str(member_path).startswith(str(extract_dir.resolve())):
                    raise RuntimeError(f"Unsafe path in update zip: {member.filename}")
            z.extractall(extract_dir)

        if platform.system() == "Darwin":
            # sys.executable: HD-Tracker.app/Contents/MacOS/HD-Tracker
            app_bundle = Path(sys.executable).resolve().parent.parent.parent
            if app_bundle.name != "HD-Tracker.app":
                raise RuntimeError(f"Unexpected app bundle name: {app_bundle.name}")
            install_dir = app_bundle.parent
            _apply_mac(app_bundle, install_dir, tmp_dir, extract_dir)
        else:
            install_dir = Path(sys.executable).resolve().parent
            new_files = extract_dir / "HD-Tracker"
            if not new_files.exists():
                new_files = extract_dir
            _apply_windows(install_dir, tmp_dir, new_files)

    except Exception:
        log.exception("Failed to apply update")
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise
