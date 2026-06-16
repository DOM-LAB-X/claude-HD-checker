"""HD Clearance Tracker — macOS window app."""
import asyncio
import os
import random
import sqlite3
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

# ── Frozen-app setup (must run before any network/playwright imports) ─────────
if getattr(sys, "frozen", False):
    # Use the standard playwright browser cache so that `playwright install webkit`
    # (run by the user or by our auto-install) is found without any extra steps.
    _browsers_dir = Path.home() / "Library" / "Caches" / "ms-playwright"
    _browsers_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(_browsers_dir))
    # Fix SSL certificate verification — PyInstaller loses the system CA bundle.
    try:
        import certifi
        os.environ.setdefault("SSL_CERT_FILE", certifi.where())
        os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())
    except ImportError:
        pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from src.config import BUNDLE_DIR, PROJECT_ROOT, _ensure_user_file, load_config, save_config
from src.logging_setup import setup_logging
from src.notifier import is_valid_discord_webhook, send_discord_message
from src.run_cycle import run_cycle
from src.watchlist import InvalidProductUrlError, load_watchlist, normalize_product_input, write_watchlist

log = setup_logging()


def _fmt_price(cents):
    return f"${cents / 100:.2f}" if cents is not None else "—"


def _version() -> str:
    try:
        return (BUNDLE_DIR / "version.txt").read_text().strip()
    except Exception:
        return ""


def _ensure_webkit() -> bool:
    """Install webkit if not already present in PLAYWRIGHT_BROWSERS_PATH."""
    if not getattr(sys, "frozen", False):
        return True  # dev mode — assume playwright install webkit was run

    browsers_dir = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", ""))
    if not browsers_dir or not browsers_dir.is_dir():
        return False

    if any(browsers_dir.glob("webkit-*")):
        log.info("webkit already installed at %s", browsers_dir)
        return True

    # Prefer the playwright driver bundled inside the .app, fall back to
    # whatever the user has on their PATH (e.g. from `pip install playwright`).
    bundled = Path(sys._MEIPASS) / "playwright" / "driver" / "playwright"
    if bundled.exists():
        try:
            os.chmod(bundled, 0o755)
        except Exception:
            pass
        install_cmd = [str(bundled), "install", "webkit"]
    else:
        import shutil as _shutil
        system_pw = _shutil.which("playwright")
        if system_pw:
            log.info("bundled driver not found, using system playwright: %s", system_pw)
            install_cmd = [system_pw, "install", "webkit"]
        else:
            log.warning("playwright not found (bundled: %s, system: not in PATH)", bundled)
            return False

    log.info("Installing webkit to %s", browsers_dir)
    try:
        env = {**os.environ, "PLAYWRIGHT_BROWSERS_PATH": str(browsers_dir)}
        result = subprocess.run(
            install_cmd,
            env=env,
            capture_output=True,
            timeout=300,
            text=True,
        )
        if result.returncode == 0:
            log.info("webkit installed successfully")
            return True
        log.error("webkit install stderr: %s", result.stderr)
        return False
    except Exception:
        log.exception("webkit install failed")
        return False


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self._config = load_config()
        ver = _version()
        self.title(f"HD Clearance Tracker{f'  v{ver}' if ver else ''}")
        self.geometry("640x680")
        self.minsize(520, 520)

        self._running = False
        self._webkit_ready = not getattr(sys, "frozen", False)
        self._status_text = tk.StringVar(value="Idle")

        self._build_ui()
        self._load_products()
        self._start_scheduler()
        self._poll_status()

        if getattr(sys, "frozen", False):
            threading.Thread(target=self._setup_browser, daemon=True).start()

    def _setup_browser(self):
        self._set_status("Setting up browser (first run, ~1 min)…", "orange")
        ok = _ensure_webkit()
        self._webkit_ready = ok
        if ok:
            self._set_status("Idle", "gray")
        else:
            self._set_status("Browser setup failed", "red")
            self.after(0, lambda: messagebox.showwarning(
                "Browser Setup Failed",
                "Could not install the WebKit browser component automatically.\n\n"
                "Open Terminal and run:\n    playwright install webkit\n\n"
                "Then relaunch the app.",
                parent=self,
            ))

    # ── UI layout ─────────────────────────────────────────────────────────────

    def _build_ui(self):
        # ── Status / header ───────────────────────────────────────────────────
        hdr = ttk.Frame(self, padding=(16, 14, 16, 0))
        hdr.pack(fill="x")

        left = ttk.Frame(hdr)
        left.pack(side="left", fill="x", expand=True)

        self._status_lbl = ttk.Label(left, textvariable=self._status_text, font=("", 12))
        self._status_lbl.pack(side="left")

        self._run_btn = ttk.Button(hdr, text="▶  Run Now", command=self._run_now)
        self._run_btn.pack(side="right")

        sched_text = "Scheduled: " + "  ·  ".join(self._config.schedule_times)
        ttk.Label(self, text=sched_text, foreground="#888", font=("", 10)).pack(
            anchor="w", padx=16, pady=(2, 8)
        )

        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=16, pady=(0, 10))

        # ── Product list ──────────────────────────────────────────────────────
        ttk.Label(self, text="Tracked Products", font=("", 13, "bold")).pack(
            anchor="w", padx=16
        )

        tree_wrap = ttk.Frame(self, padding=(16, 6, 16, 0))
        tree_wrap.pack(fill="both", expand=True)

        cols = ("item", "name", "online", "clearance")
        self._tree = ttk.Treeview(
            tree_wrap, columns=cols, show="headings", selectmode="browse", height=8
        )
        for col, heading, width, anchor in [
            ("item",      "Item #",    90,  "w"),
            ("name",      "Name",      285, "w"),
            ("online",    "Online",    80,  "e"),
            ("clearance", "Clearance", 95,  "e"),
        ]:
            self._tree.heading(col, text=heading)
            self._tree.column(col, width=width, anchor=anchor, stretch=(col == "name"))

        vsb = ttk.Scrollbar(tree_wrap, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        btn_row = ttk.Frame(self, padding=(16, 4, 16, 0))
        btn_row.pack(fill="x")
        ttk.Button(btn_row, text="Remove Selected", command=self._remove_selected).pack(side="right")

        # ── Add product ───────────────────────────────────────────────────────
        ttk.Label(
            self, text="Add product — item number or Home Depot URL:", padding=(16, 6, 16, 0)
        ).pack(anchor="w")

        add_row = ttk.Frame(self, padding=(16, 4, 16, 0))
        add_row.pack(fill="x")
        self._add_var = tk.StringVar()
        entry = ttk.Entry(add_row, textvariable=self._add_var, font=("", 12))
        entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        entry.bind("<Return>", lambda _: self._add_product())
        ttk.Button(add_row, text="Add", command=self._add_product).pack(side="left")

        self._add_msg = ttk.Label(self, text="", foreground="red", padding=(16, 2, 16, 0))
        self._add_msg.pack(anchor="w")

        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=16, pady=10)

        # ── Discord alerts ────────────────────────────────────────────────────
        ttk.Label(self, text="Discord Alerts", font=("", 13, "bold")).pack(
            anchor="w", padx=16
        )

        wh_row = ttk.Frame(self, padding=(16, 6, 16, 0))
        wh_row.pack(fill="x")
        ttk.Label(wh_row, text="Webhook URL:").pack(side="left", padx=(0, 6))
        self._wh_var = tk.StringVar(value=self._config.alerts.get("discord_webhook_url", ""))
        self._wh_show = tk.BooleanVar(value=False)
        self._wh_entry = ttk.Entry(wh_row, textvariable=self._wh_var, show="*")
        self._wh_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        ttk.Checkbutton(
            wh_row, text="Show",
            variable=self._wh_show,
            command=lambda: self._wh_entry.configure(show="" if self._wh_show.get() else "*"),
        ).pack(side="left", padx=(0, 6))
        ttk.Button(wh_row, text="Test", command=self._test_webhook).pack(side="left")

        obs_row = ttk.Frame(self, padding=(16, 4, 16, 0))
        obs_row.pack(fill="x")
        self._obs_var = tk.BooleanVar(value=self._config.alerts.get("observation_only", True))
        ttk.Checkbutton(
            obs_row,
            text="Observation-only mode (detect changes but don't send alerts)",
            variable=self._obs_var,
        ).pack(side="left")

        footer = ttk.Frame(self, padding=(16, 6, 16, 14))
        footer.pack(fill="x")
        self._alert_msg = ttk.Label(footer, text="", foreground="gray")
        self._alert_msg.pack(side="left")
        ttk.Button(footer, text="Save Settings", command=self._save_alerts).pack(side="right")

    # ── Data ──────────────────────────────────────────────────────────────────

    def _load_products(self):
        self._tree.delete(*self._tree.get_children())
        try:
            wl_path = str(_ensure_user_file(self._config.watchlist_path))
            entries = load_watchlist(wl_path)
        except Exception:
            log.exception("Failed to load watchlist")
            return

        db_path = PROJECT_ROOT / self._config.db_path
        conn = None
        if db_path.exists():
            try:
                conn = sqlite3.connect(db_path)
            except Exception:
                pass

        for e in entries:
            name = f"#{e.internet_number}"
            online = "—"
            clearance = "—"
            if conn:
                row = conn.execute(
                    "SELECT name FROM products WHERE internet_number = ?",
                    (e.internet_number,),
                ).fetchone()
                if row and row[0]:
                    name = row[0][:55]

                obs = conn.execute(
                    """
                    SELECT online_price_cents, clearance_price_cents
                    FROM price_observations
                    WHERE product_id = (SELECT id FROM products WHERE internet_number = ?)
                    ORDER BY checked_at DESC LIMIT 1
                    """,
                    (e.internet_number,),
                ).fetchone()
                if obs:
                    online = _fmt_price(obs[0])
                    clearance = _fmt_price(obs[1]) if obs[1] else "No clearance"

            self._tree.insert(
                "", "end",
                iid=e.internet_number,
                values=(e.internet_number, name, online, clearance),
            )

        if conn:
            conn.close()

    # ── Actions ───────────────────────────────────────────────────────────────

    def _add_product(self):
        raw = self._add_var.get().strip()
        if not raw:
            return
        try:
            url = normalize_product_input(raw)
        except InvalidProductUrlError as e:
            self._add_msg.configure(text=str(e), foreground="red")
            return

        wl_path = str(_ensure_user_file(self._config.watchlist_path))
        try:
            entries = load_watchlist(wl_path)
        except Exception:
            entries = []

        existing = [e.url for e in entries]
        if url in existing:
            self._add_msg.configure(text="Already in watchlist.", foreground="orange")
            return

        write_watchlist(wl_path, existing + [url])
        self._add_var.set("")
        self._add_msg.configure(text="Added!", foreground="green")
        self.after(2000, lambda: self._add_msg.configure(text=""))
        self._load_products()

    def _remove_selected(self):
        sel = self._tree.selection()
        if not sel:
            return
        item_id = sel[0]
        wl_path = str(_ensure_user_file(self._config.watchlist_path))
        entries = load_watchlist(wl_path)
        write_watchlist(wl_path, [e.url for e in entries if e.internet_number != item_id])
        self._load_products()

    def _run_now(self):
        if self._running:
            return
        if not self._webkit_ready:
            messagebox.showinfo(
                "Not Ready",
                "Browser is still being set up. Please wait a moment.",
                parent=self,
            )
            return
        threading.Thread(target=self._do_run_cycle, daemon=True).start()

    def _do_run_cycle(self):
        self._running = True
        self._set_status("Running check…", "orange")
        try:
            cfg = load_config()
            asyncio.run(run_cycle(cfg))
            self._set_status("Idle", "gray")
            self.after(0, self._load_products)
        except Exception:
            log.exception("Run cycle failed")
            self._set_status("Last check failed — see log for details", "red")
        finally:
            self._running = False

    def _test_webhook(self):
        url = self._wh_var.get().strip()
        if not is_valid_discord_webhook(url):
            messagebox.showerror(
                "Invalid Webhook URL",
                "The URL doesn't look like a Discord webhook.\n\n"
                "It should start with:\n"
                "  https://discord.com/api/webhooks/…\n\n"
                "Copy it from Discord: Server Settings → Integrations → Webhooks.",
                parent=self,
            )
            return
        self._alert_msg.configure(text="Sending test…", foreground="gray")
        self.update_idletasks()

        def _send():
            ok = send_discord_message(url, "HD Clearance Tracker: test alert ✓")
            if ok:
                self.after(0, lambda: self._alert_msg.configure(
                    text="Test message sent!", foreground="green"
                ))
            else:
                self.after(0, lambda: messagebox.showerror(
                    "Send Failed",
                    "Could not send the test message.\n\n"
                    "Check the log file for the exact error — look for 'Discord webhook'.",
                    parent=self,
                ))
                self.after(0, lambda: self._alert_msg.configure(text="", foreground="gray"))

        threading.Thread(target=_send, daemon=True).start()

    def _save_alerts(self):
        url = self._wh_var.get().strip()
        if url and not is_valid_discord_webhook(url):
            messagebox.showerror(
                "Invalid Webhook URL",
                "The URL must look like:\nhttps://discord.com/api/webhooks/…",
                parent=self,
            )
            return
        self._config.alerts["discord_webhook_url"] = url
        self._config.alerts["observation_only"] = self._obs_var.get()
        save_config(self._config)
        self._alert_msg.configure(text="Settings saved.", foreground="green")
        self.after(2000, lambda: self._alert_msg.configure(text=""))

    # ── Utilities ─────────────────────────────────────────────────────────────

    def _set_status(self, text: str, color: str = "gray"):
        def _update():
            self._status_text.set(text)
            self._status_lbl.configure(foreground=color)
            self._run_btn.configure(state="disabled" if self._running else "normal")
        self.after(0, _update)

    def _poll_status(self):
        self._run_btn.configure(state="disabled" if self._running else "normal")
        self.after(1500, self._poll_status)

    def _start_scheduler(self):
        self._scheduler = BackgroundScheduler(timezone=self._config.timezone)
        for t in self._config.schedule_times:
            h, m = t.split(":")
            self._scheduler.add_job(
                self._scheduled_run,
                CronTrigger(hour=int(h), minute=int(m)),
            )
        self._scheduler.start()
        log.info("Scheduler started: %s", self._config.schedule_times)

    def _scheduled_run(self):
        if not self._webkit_ready:
            log.warning("Skipping scheduled run — browser not ready")
            return
        cfg = load_config()
        if cfg.jitter_minutes:
            time.sleep(random.uniform(0, cfg.jitter_minutes * 60))
        self._do_run_cycle()

    def on_close(self):
        self._scheduler.shutdown(wait=False)
        self.destroy()


def main():
    app = App()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    log.info("HD Clearance Tracker (macOS) started")
    app.mainloop()


if __name__ == "__main__":
    main()
