"""Tkinter settings window: manage the watchlist and Discord alert settings.

Opened from the tray menu. Uses only the standard library (tkinter) so no
extra dependency is needed.
"""
import sqlite3
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from src import db
from src.config import PROJECT_ROOT, _ensure_user_file, load_config, save_config
from src.notifier import is_valid_discord_webhook, send_discord_message
from src.watchlist import InvalidProductUrlError, load_watchlist, validate_product_url, write_watchlist


def _product_label(conn, internet_number: str) -> str:
    row = conn.execute(
        "SELECT name FROM products WHERE internet_number = ?", (internet_number,)
    ).fetchone()
    if row and row[0]:
        return f"{row[0][:60]}  (#{internet_number})"
    return f"#{internet_number}"


def open_settings_window(parent=None):
    config = load_config()
    watchlist_path = str(_ensure_user_file(config.watchlist_path))

    win = tk.Toplevel(parent) if parent else tk.Tk()
    win.title("HD Clearance Tracker - Settings")
    win.geometry("520x480")
    win.resizable(False, False)

    notebook = ttk.Notebook(win)
    notebook.pack(fill="both", expand=True, padx=8, pady=8)

    # --- Watchlist tab ---
    watch_frame = ttk.Frame(notebook)
    notebook.add(watch_frame, text="Watchlist")

    ttk.Label(watch_frame, text="Tracked products:").pack(anchor="w", padx=8, pady=(8, 0))

    list_frame = ttk.Frame(watch_frame)
    list_frame.pack(fill="both", expand=True, padx=8, pady=4)

    listbox = tk.Listbox(list_frame)
    scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=listbox.yview)
    listbox.configure(yscrollcommand=scrollbar.set)
    listbox.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")

    entries = []  # list of WatchlistEntry, parallel to listbox rows

    def refresh_list():
        listbox.delete(0, tk.END)
        entries.clear()
        try:
            db_path = PROJECT_ROOT / config.db_path
            conn = sqlite3.connect(db_path) if db_path.exists() else None
            for entry in load_watchlist(watchlist_path):
                entries.append(entry)
                label = _product_label(conn, entry.internet_number) if conn else f"#{entry.internet_number}"
                listbox.insert(tk.END, f"{label}  -  {entry.url}")
            if conn:
                conn.close()
        except InvalidProductUrlError as e:
            messagebox.showerror("Watchlist error", str(e))

    refresh_list()

    add_frame = ttk.Frame(watch_frame)
    add_frame.pack(fill="x", padx=8, pady=4)
    ttk.Label(add_frame, text="Add product URL:").pack(anchor="w")
    url_var = tk.StringVar()
    url_entry = ttk.Entry(add_frame, textvariable=url_var)
    url_entry.pack(fill="x", pady=2)
    ttk.Label(add_frame, text="Paste a homedepot.com/p/.../<item#> product page URL",
              foreground="gray").pack(anchor="w")

    def add_product():
        url = url_var.get().strip()
        if not url:
            return
        try:
            validated = validate_product_url(url)
        except InvalidProductUrlError as e:
            messagebox.showerror("Invalid URL", str(e))
            return
        urls = [e.url for e in entries] + [validated]
        write_watchlist(watchlist_path, urls)
        url_var.set("")
        refresh_list()

    def remove_selected():
        sel = listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        urls = [e.url for i, e in enumerate(entries) if i != idx]
        write_watchlist(watchlist_path, urls)
        refresh_list()

    btn_frame = ttk.Frame(watch_frame)
    btn_frame.pack(fill="x", padx=8, pady=(0, 8))
    ttk.Button(btn_frame, text="Add", command=add_product).pack(side="left")
    ttk.Button(btn_frame, text="Remove selected", command=remove_selected).pack(side="left", padx=4)

    # --- Alerts tab ---
    alerts_frame = ttk.Frame(notebook)
    notebook.add(alerts_frame, text="Alerts")

    ttk.Label(alerts_frame, text="Discord webhook URL:").pack(anchor="w", padx=8, pady=(12, 0))
    webhook_var = tk.StringVar(value=config.alerts.get("discord_webhook_url", ""))
    webhook_entry = ttk.Entry(alerts_frame, textvariable=webhook_var, show="*")
    webhook_entry.pack(fill="x", padx=8, pady=2)

    def toggle_show():
        webhook_entry.configure(show="" if show_var.get() else "*")

    show_var = tk.BooleanVar(value=False)
    ttk.Checkbutton(alerts_frame, text="Show", variable=show_var, command=toggle_show).pack(anchor="w", padx=8)

    ttk.Label(
        alerts_frame,
        text="Create one in Discord: Server Settings > Integrations > Webhooks.\n"
             "Keep this URL private - anyone with it can post to your channel.",
        foreground="gray", justify="left",
    ).pack(anchor="w", padx=8, pady=(0, 8))

    observation_var = tk.BooleanVar(value=config.alerts.get("observation_only", True))
    ttk.Checkbutton(
        alerts_frame,
        text="Observation-only mode (detect price changes but don't send alerts)",
        variable=observation_var,
    ).pack(anchor="w", padx=8, pady=4)

    status_label = ttk.Label(alerts_frame, text="", foreground="gray")
    status_label.pack(anchor="w", padx=8)

    def test_webhook():
        url = webhook_var.get().strip()
        if not is_valid_discord_webhook(url):
            status_label.configure(text="Not a valid Discord webhook URL.", foreground="red")
            return
        ok = send_discord_message(url, "HD Clearance Tracker: test alert. If you see this, alerts are working!")
        status_label.configure(
            text="Test message sent!" if ok else "Failed to send - check the URL and your connection.",
            foreground="green" if ok else "red",
        )

    def save_settings():
        url = webhook_var.get().strip()
        if url and not is_valid_discord_webhook(url):
            messagebox.showerror(
                "Invalid webhook",
                "That doesn't look like a Discord webhook URL "
                "(expected https://discord.com/api/webhooks/...).",
            )
            return
        config.alerts["discord_webhook_url"] = url
        config.alerts["observation_only"] = observation_var.get()
        save_config(config)
        status_label.configure(text="Settings saved.", foreground="green")

    btns = ttk.Frame(alerts_frame)
    btns.pack(fill="x", padx=8, pady=8)
    ttk.Button(btns, text="Send test alert", command=test_webhook).pack(side="left")
    ttk.Button(btns, text="Save", command=save_settings).pack(side="left", padx=4)

    return win


if __name__ == "__main__":
    open_settings_window().mainloop()
