"""System tray app for the HD Clearance Tracker.

Runs the 3x/day scheduled price-check cycle in the background and shows a
tray icon with quick actions (run now, settings, open data folder, quit).
This is the entry point used when packaged into a Windows .exe via
build_exe.bat.
"""
import asyncio
import platform
import random
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path

import pystray
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from src.config import BUNDLE_DIR, PROJECT_ROOT, load_config
from src.gui import open_settings_window
from src.run_cycle import run_cycle

ICON_PATH = BUNDLE_DIR / "icon.ico"

startup_config = load_config()
status = {"text": "Idle", "running": False}


def _run_cycle_sync(jitter=False):
    if status["running"]:
        return
    status["running"] = True
    # Reload config each run so changes made in the Settings window
    # (Discord webhook, observation-only, watchlist) take effect immediately.
    config = load_config()
    if jitter and config.jitter_minutes:
        wait_s = random.uniform(0, config.jitter_minutes * 60)
        status["text"] = f"Waiting {wait_s/60:.0f}min (jitter) before check..."
        time.sleep(wait_s)
    status["text"] = "Running check..."
    try:
        asyncio.run(run_cycle(config))
        status["text"] = "Idle (last run OK)"
    except Exception as e:
        status["text"] = f"Idle (last run failed: {e})"
    finally:
        status["running"] = False


def run_now(icon=None, item=None):
    threading.Thread(target=_run_cycle_sync, daemon=True).start()


def open_data_folder(icon=None, item=None):
    data_dir = PROJECT_ROOT / "data"
    if platform.system() == "Windows":
        subprocess.Popen(["explorer", str(data_dir)])
    elif platform.system() == "Darwin":
        subprocess.Popen(["open", str(data_dir)])
    else:
        subprocess.Popen(["xdg-open", str(data_dir)])


def open_settings(icon=None, item=None):
    # Tkinter windows must be created on the main thread; pystray calls menu
    # actions from its own thread, so hand off via root.after().
    root.after(0, lambda: open_settings_window(root))


def quit_app(icon, item):
    scheduler.shutdown(wait=False)
    icon.stop()
    root.after(0, root.quit)


def build_menu():
    return pystray.Menu(
        pystray.MenuItem(lambda item: f"Status: {status['text']}", None, enabled=False),
        pystray.MenuItem("Run check now", run_now),
        pystray.MenuItem("Manage watchlist & alerts", open_settings),
        pystray.MenuItem("Open data folder", open_data_folder),
        pystray.MenuItem("Quit", quit_app),
    )


scheduler = BackgroundScheduler(timezone=startup_config.timezone)
for time_str in startup_config.schedule_times:
    hour, minute = time_str.split(":")
    scheduler.add_job(_run_cycle_sync, CronTrigger(hour=int(hour), minute=int(minute)), kwargs={"jitter": True})

root = tk.Tk()
root.withdraw()  # no main window - tray icon + on-demand settings window only


def main():
    scheduler.start()
    image = Image.open(ICON_PATH)
    icon = pystray.Icon("HD Clearance Tracker", image, "HD Clearance Tracker", menu=build_menu())
    threading.Thread(target=icon.run, daemon=True).start()
    root.mainloop()


if __name__ == "__main__":
    main()
