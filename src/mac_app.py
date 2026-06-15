"""HD Clearance Tracker — macOS window app.

A proper GUI window (shows in Dock) that replaces the tray-icon-only approach
used on Windows. All functionality is in one window: product list, add/remove,
scheduled checks, Discord alerts.
"""
import asyncio
import os
import random
import sqlite3
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

# ── Frozen-app setup (must run before any network imports) ────────────────────
if getattr(sys, "frozen", False):
    _meipass = Path(sys._MEIPASS)
    # Always set the Playwright browser path so it finds (or clearly errors on)
    # the bundled webkit binary.
    os.environ.setdefault(
        "PLAYWRIGHT_BROWSERS_PATH", str(_meipass / "playwright-browsers")
    )
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

from src import db
from src.config import BUNDLE_DIR, PROJECT_ROOT, _ensure_user_file, load_config, save_config
from src.logging_setup import setup_logging
from src.notifier import is_valid_discord_webhook, send_discord_message
from src.run_cycle import run_cycle
from src.watchlist import InvalidProductUrlError, load_watchlist, normalize_product_input, write_watchlist

log = setup_logging()

# ── Helpers ───────────────────────────────────────────────────────────────────

def _fmt_price(cents):
    return f"${cents / 100:.2f}" if cents is not None else "—"


def _version() -> str:
    try:
        return (BUNDLE_DIR / "version.txt").read_text().strip()
    except Exception:
        return ""


# ── Main window ───────────────────────────────────────────────────────────────

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self._config = load_config()
        ver = _version()
        self.title(f"HD Clearance Tracker{f'  v{ver}' if ver else ''}")
        self.geometry("640x660")
        self.minsize(520, 500)

        self._running = False
        self._status_text = tk.StringVar(value="Status: Idle")

        self._build_ui()
        self._load_products()
        self._start_scheduler()
        self._poll_status()

    # ── UI layout ─────────────────────────────────────────────────────────────

    def _build_ui(self):
        P = dict(padx=14, pady=5)

        # ── Status bar ────────────────────────────────────────────────────────
        top = ttk.Frame(self)
        top.pack(fill="x", **P)
        ttk.Label(top, textvariable=self._status_text, foreground="gray").pack(side="left")
        self._run_btn = ttk.Button(top, text="▶  Run Now", command=self._run_now)
        self._run_btn.pack(side="right")

        sched = "Scheduled: " + "  ·  ".join(self._config.schedule_times)
        ttk.Label(self, text=sched, foreground="gray", font=("", 10)).pack(
            anchor="w", padx=14, pady=(0, 2)
        )

        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=14, pady=6)

        # ── Product list ──────────────────────────────────────────────────────
        ttk.Label(self, text="Tracked Products", font=("", 13, "bold")).pack(
            anchor="w", padx=14, pady=(0, 4)
        )

        tree_wrap = ttk.Frame(self)
        tree_wrap.pack(fill="both", expand=True, padx=14, pady=(0, 2))

        cols = ("item", "name", "online", "clearance")
        self._tree = ttk.Treeview(
            tree_wrap, columns=cols, show="headings", selectmode="browse", height=8
        )
        for col, heading, width, anchor in [
            ("item",      "Item #",    90,  "w"),
            ("name",      "Name",      310, "w"),
            ("online",    "Online",    80,  "e"),
            ("clearance", "Clearance", 95,  "e"),
        ]:
            self._tree.heading(col, text=heading)
            self._tree.column(col, width=width, anchor=anchor, stretch=(col == "name"))

        vsb = ttk.Scrollbar(tree_wrap, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        rm_row = ttk.Frame(self)
        rm_row.pack(fill="x", padx=14, pady=(0, 4))
        ttk.Button(rm_row, text="Remove selected", command=self._remove_selected).pack(side="right")

        # ── Add product ───────────────────────────────────────────────────────
        ttk.Label(
            self, text="Add product — paste item number or any Home Depot URL:"
        ).pack(anchor="w", padx=14)

        add_row = ttk.Frame(self)
        add_row.pack(fill="x", padx=14, pady=(3, 4))
        self._add_var = tk.StringVar()
        entry = ttk.Entry(add_row, textvariable=self._add_var, font=("", 12))
        entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        entry.bind("<Return>", lambda _: self._add_product())
        ttk.Button(add_row, text="Add", command=self._add_product).pack(side="left")

        self._add_msg = ttk.Label(self, text="", foreground="red")
        self._add_msg.pack(anchor="w", padx=14)

        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=14, pady=8)

        # ── Discord alerts ────────────────────────────────────────────────────
        ttk.Label(self, text="Discord Alerts", font=("", 13, "bold")).pack(
            anchor="w", padx=14, pady=(0, 4)
        )
        ttk.Label(self, text="Webhook URL:").pack(anchor="w", padx=14)

        wh_row = ttk.Frame(self)
        wh_row.pack(fill="x", padx=14, pady=(2, 4))
        self._wh_var = tk.StringVar(value=self._config.alerts.get("discord_webhook_url", ""))
        self._wh_show = tk.BooleanVar(value=False)
        self._wh_entry = ttk.Entry(wh_row, textvariable=self._wh_var, show="*")
        self._wh_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        ttk.Checkbutton(
            wh_row, text="Show",
            variable=self._wh_show,
            command=lambda: self._wh_entry.configure(show="" if self._wh_show.get() else "*"),
        ).pack(side="left", padx=(0, 6))
        ttk.Button(wh_row, text="Send test", command=self._test_webhook).pack(side="left")

        obs_row = ttk.Frame(self)
        obs_row.pack(fill="x", padx=14, pady=(0, 4))
        self._obs_var = tk.BooleanVar(value=self._config.alerts.get("observation_only", True))
        ttk.Checkbutton(
            obs_row,
            text="Observation-only mode (detect price changes but don't send alerts)",
            variable=self._obs_var,
        ).pack(side="left")

        footer = ttk.Frame(self)
        footer.pack(fill="x", padx=14, pady=(2, 14))
        self._alert_msg = ttk.Label(footer, text="", foreground="gray")
        self._alert_msg.pack(side="left")
        ttk.Button(footer, text="Save settings", command=self._save_alerts).pack(side="right")

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
        threading.Thread(target=self._do_run_cycle, daemon=True).start()

    def _do_run_cycle(self):
        self._running = True
        self._set_status("Running check...")
        try:
            cfg = load_config()
            asyncio.run(run_cycle(cfg))
            self._set_status("Last run: OK")
            self.after(0, self._load_products)
        except Exception as e:
            log.exception("Run cycle failed")
            self._set_status(f"Last run failed: {e}")
        finally:
            self._running = False

    def _test_webhook(self):
        url = self._wh_var.get().strip()
        if not is_valid_discord_webhook(url):
            self._alert_msg.configure(
                text="Not a valid Discord webhook URL.", foreground="red"
            )
            return
        self._alert_msg.configure(text="Sending test...", foreground="gray")
        self.update_idletasks()

        def _send():
            ok = send_discord_message(url, "HD Clearance Tracker: test alert ✓")
            self.after(
                0,
                lambda: self._alert_msg.configure(
                    text="Test sent!" if ok else "Failed — check the URL and your connection.",
                    foreground="green" if ok else "red",
                ),
            )

        threading.Thread(target=_send, daemon=True).start()

    def _save_alerts(self):
        url = self._wh_var.get().strip()
        if url and not is_valid_discord_webhook(url):
            messagebox.showerror(
                "Invalid webhook",
                "Expected: https://discord.com/api/webhooks/…",
                parent=self,
            )
            return
        self._config.alerts["discord_webhook_url"] = url
        self._config.alerts["observation_only"] = self._obs_var.get()
        save_config(self._config)
        self._alert_msg.configure(text="Saved.", foreground="green")
        self.after(2000, lambda: self._alert_msg.configure(text=""))

    # ── Utilities ─────────────────────────────────────────────────────────────

    def _set_status(self, text: str):
        self.after(0, lambda: self._status_text.set(f"Status: {text}"))
        self.after(0, lambda: self._run_btn.configure(
            state="disabled" if self._running else "normal"
        ))

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
