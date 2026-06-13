# HD Clearance Tracker

Tracks Home Depot in-store clearance prices for items in `watchlist.txt`
across stores 1701, 1702, 1706, 1707.

## Windows setup (one-time)

1. Install Python 3.10+ from https://www.python.org/downloads/
   During install, check **"Add python.exe to PATH"**.
2. Double-click **`setup.bat`**. This creates a virtual environment, installs
   dependencies, and downloads the WebKit browser used for checking prices.
3. Double-click **`build_exe.bat`**. This builds `dist\HD-Tracker.exe` and
   adds a **"HD Clearance Tracker"** shortcut/icon to your Desktop.

## Usage (the app)

Double-click the **"HD Clearance Tracker"** desktop icon. It runs in the
system tray (bottom-right of the taskbar) — click the icon for a menu:

- **Status** — shows whether a check is running
- **Run check now** — runs an immediate cycle across all stores/products
- **Manage watchlist & alerts** — opens a window where you can add/remove
  tracked products and set up Discord alerts (see below)
- **Open data folder** — opens the folder with `tracker.sqlite3`
- **Quit** — stops the tracker

While running, it automatically checks prices at the times configured in
`config.yaml` (default: 01:00, 09:00, 17:00 Hawaii time, with jitter). Leave
it running in the tray for it to keep checking on schedule.

`config.yaml` and `watchlist.txt` are copied next to `HD-Tracker.exe` (in
`dist\`) the first time it runs — edit those copies to change settings.

### Managing the watchlist (UI)

Open **"Manage watchlist & alerts"** from the tray menu, then the
**Watchlist** tab:

- Paste a Home Depot product page URL (the page must contain `/p/` and end
  with the item's Internet #, e.g.
  `https://www.homedepot.com/p/.../301424967`) and click **Add**.
- Select an item in the list and click **Remove selected** to stop tracking
  it.

Changes take effect on the next scheduled check (or click **Run check now**).

### Discord alerts (UI)

Open **"Manage watchlist & alerts"** from the tray menu, then the **Alerts**
tab:

1. In Discord, go to **Server Settings > Integrations > Webhooks** and create
   a webhook for the channel you want alerts in. Copy its URL.
2. Paste the URL into **Discord webhook URL** (click **Show** to verify
   what you typed).
3. Click **Send test alert** to confirm it works.
4. Uncheck **Observation-only mode** to start sending real alerts for price
   drops, new clearance finds, and big inter-store price differences. While
   checked, changes are still detected and logged but no Discord message is
   sent.
5. Click **Save**.

Keep your webhook URL private — anyone who has it can post messages to that
Discord channel.

## Usage (without building the exe)

- **`run_once.bat`** — runs a single check cycle and prints results to a
  console window. Good for testing before building the app.
- **`run.bat`** — starts the scheduler in a console window (closes the
  tracker when the window is closed).

## Configuration

- **`watchlist.txt`** — one Home Depot product URL per line. Add/remove
  products here.
- **`config.yaml`** — stores, schedule times, alert thresholds, delays.
  `alerts.observation_only: true` means price changes are detected and saved
  but no notifications are sent yet.

## Data

Results are saved to `data/tracker.sqlite3` (SQLite database) with tables:
- `products` — tracked items
- `price_observations` — every price check, per product/store/time
- `change_events` — detected price drops, first-clearance finds, etc.
- `runs` — summary of each check cycle

You can open this file with any SQLite browser (e.g. DB Browser for SQLite)
to view price history.
