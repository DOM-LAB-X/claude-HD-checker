# HD Clearance Tracker

Tracks Home Depot in-store clearance prices for items in `watchlist.txt`
across stores 1701, 1702, 1706, 1707.

## Installation (end users)

1. Download the latest **`HD-Tracker.zip`** from the
   [Releases page](https://github.com/DOM-LAB-X/claude-HD-checker/releases/latest).
2. Extract the zip anywhere (e.g. `C:\Users\You\HD-Tracker\`).
3. Double-click **`HD-Tracker.exe`** inside the extracted folder.

No Python or other software needed.

## Usage

The app runs in the system tray (bottom-right of the taskbar). Click the
icon for a menu:

- **Status** — shows whether a check is running
- **Update available (vX.X.X) — click to install** — appears when a new
  version is available; clicking it downloads and applies the update
  automatically, then relaunches the app
- **Run check now** — runs an immediate cycle across all stores/products
- **Manage watchlist & alerts** — opens a window to add/remove tracked
  products and set up Discord alerts (see below)
- **Open data folder** — opens the folder with `tracker.sqlite3`
- **Quit** — stops the tracker

The app checks prices automatically at the times in `config.yaml` (default:
01:00, 09:00, 17:00 Hawaii time, with jitter). Leave it running in the tray.

`config.yaml` and `watchlist.txt` live next to `HD-Tracker.exe` — edit
those files to change settings or the watchlist directly.

### Auto-updates

When you open the tray menu and a new version has been released, an
**"Update available"** item appears at the top. Click it to download and
install the update silently — the app restarts automatically. Your
`config.yaml`, `watchlist.txt`, and price history are never overwritten.

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

## Configuration

- **`watchlist.txt`** — one Home Depot product URL per line.
- **`config.yaml`** — stores, schedule times, alert thresholds, delays.
  `alerts.observation_only: true` means price changes are detected and saved
  but no notifications are sent.

## Data

Results are saved to `data/tracker.sqlite3` (SQLite database) with tables:

- `products` — tracked items
- `price_observations` — every price check, per product/store/time
- `change_events` — detected price drops, first-clearance finds, etc.
- `runs` — summary of each check cycle

Open this file with any SQLite browser (e.g. DB Browser for SQLite) to view
price history.

---

## Developer notes

### One-time dev setup

1. Install Python 3.10+ and check **"Add python.exe to PATH"**.
2. Double-click **`setup.bat`** — creates a virtual env and installs
   dependencies.

### Publishing a release

Double-click **`make_release.bat`**. It will:

1. Ask for the new version number (e.g. `1.0.1`).
2. Update `version.txt`.
3. Build `dist\HD-Tracker\` with PyInstaller.
4. Zip it as `HD-Tracker.zip`.
5. Open the GitHub new-release page so you can tag and attach the zip.

Running users will see the **"Update available"** prompt in their tray menu
the next time they open it after you publish.

### Running from source (no exe)

- **`run_once.bat`** — single check cycle, prints to console. Good for
  testing.
- **`run.bat`** — starts the scheduler in a console window.
