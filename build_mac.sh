#!/bin/bash
# Builds HD-Tracker.app for macOS.
# Requires: venv set up via setup_mac.sh, webkit installed via playwright install webkit
set -e
cd "$(dirname "$0")"
source venv/bin/activate

# ── Icon ──────────────────────────────────────────────────────────────────────
echo "Generating macOS icon..."
python3 - <<'PYEOF'
import sys
from pathlib import Path

try:
    from PIL import Image
    img = Image.open("icon.ico").convert("RGBA")
    img.save("/tmp/hd_icon_src.png", "PNG")
    print("Converted icon.ico → /tmp/hd_icon_src.png")
except Exception as e:
    print(f"Warning: could not load icon.ico ({e}), generating placeholder icon")
    from PIL import Image, ImageDraw, ImageFont
    size = 512
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Orange circle background
    draw.ellipse([20, 20, size-20, size-20], fill=(255, 140, 0, 255))
    # "HD" text
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 200)
    except Exception:
        font = ImageFont.load_default()
    draw.text((size//2, size//2), "HD", fill=(255, 255, 255, 255), font=font, anchor="mm")
    img.save("/tmp/hd_icon_src.png", "PNG")
    print("Generated placeholder icon")
PYEOF

mkdir -p /tmp/hd_icon.iconset
for size in 16 32 64 128 256 512; do
    sips -z $size $size /tmp/hd_icon_src.png \
        --out "/tmp/hd_icon.iconset/icon_${size}x${size}.png" >/dev/null 2>&1 || true
    double=$((size * 2))
    if [ $double -le 1024 ]; then
        sips -z $double $double /tmp/hd_icon_src.png \
            --out "/tmp/hd_icon.iconset/icon_${size}x${size}@2x.png" >/dev/null 2>&1 || true
    fi
done
iconutil -c icns /tmp/hd_icon.iconset -o icon.icns 2>/dev/null && \
    echo "Created icon.icns" || { echo "iconutil failed, falling back to PNG"; cp /tmp/hd_icon_src.png icon_mac.png; }

ICON_FILE="icon.icns"
[ -f "$ICON_FILE" ] || ICON_FILE="icon_mac.png"
[ -f "$ICON_FILE" ] || ICON_FILE=""

# ── Playwright webkit ─────────────────────────────────────────────────────────
echo "Locating Playwright WebKit..."
WEBKIT_DIR=""
WEBKIT_FLAG=""
MS_CACHE="${HOME}/.cache/ms-playwright"
if [ -d "$MS_CACHE" ]; then
    WEBKIT_DIR=$(ls -d "${MS_CACHE}/webkit-"* 2>/dev/null | sort -V | tail -1)
fi
if [ -n "$WEBKIT_DIR" ] && [ -d "$WEBKIT_DIR" ]; then
    WEBKIT_NAME=$(basename "$WEBKIT_DIR")
    WEBKIT_FLAG="--add-data ${WEBKIT_DIR}:playwright-browsers/${WEBKIT_NAME}"
    echo "Bundling WebKit: $WEBKIT_NAME"
else
    echo "Warning: WebKit not found in ~/.cache/ms-playwright"
    echo "         Run 'playwright install webkit' then rebuild."
    echo "         The app will fall back to the system playwright cache at runtime."
fi

# ── PyInstaller ───────────────────────────────────────────────────────────────
echo "Building HD-Tracker.app..."

ICON_FLAG=""
[ -n "$ICON_FILE" ] && ICON_FLAG="--icon ${ICON_FILE}"

# shellcheck disable=SC2086
pyinstaller --noconfirm --onedir --windowed --name "HD-Tracker" \
    $ICON_FLAG \
    --add-data "config.yaml:." \
    --add-data "watchlist.txt:." \
    --add-data "icon.ico:." \
    --add-data "version.txt:." \
    $WEBKIT_FLAG \
    --collect-all greenlet \
    --collect-all playwright \
    --hidden-import "pystray._darwin" \
    --hidden-import "Quartz" \
    --hidden-import "AppKit" \
    src/tray_app.py

if [ $? -ne 0 ]; then
    echo "Build failed — see errors above."
    exit 1
fi

# ── Post-process: hide from Dock, set bundle ID ───────────────────────────────
PLIST="dist/HD-Tracker.app/Contents/Info.plist"
echo "Configuring app bundle..."
# Hide the Dock icon — this is a menu-bar-only app
/usr/libexec/PlistBuddy -c "Add :LSUIElement bool true" "$PLIST" 2>/dev/null || \
    /usr/libexec/PlistBuddy -c "Set :LSUIElement true" "$PLIST" 2>/dev/null || true
/usr/libexec/PlistBuddy -c "Set :CFBundleIdentifier com.domlab.hd-tracker" "$PLIST" 2>/dev/null || \
    /usr/libexec/PlistBuddy -c "Add :CFBundleIdentifier string com.domlab.hd-tracker" "$PLIST" 2>/dev/null || true

echo ""
echo "Build complete: dist/HD-Tracker.app"
echo "To test:  open dist/HD-Tracker.app"
echo ""
echo "Note: macOS may block the app on first launch (Gatekeeper)."
echo "If that happens, right-click the .app and choose Open, or run:"
echo "  xattr -cr dist/HD-Tracker.app"
