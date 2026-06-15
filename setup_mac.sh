#!/bin/bash
set -e
cd "$(dirname "$0")"

if ! command -v python3 &>/dev/null; then
    echo "Python 3 not found."
    echo "Install from https://www.python.org/downloads/macos/ and make sure to"
    echo "check 'Add to PATH'. Homebrew users: brew install python-tk@3.12"
    exit 1
fi

echo "Creating virtual environment..."
python3 -m venv venv

echo "Installing dependencies..."
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
# pystray on macOS requires PyObjC (AppKit + Quartz)
pip install pyobjc-framework-Quartz pyobjc-framework-AppKit

echo "Installing WebKit browser for Playwright..."
playwright install webkit

echo ""
echo "Setup complete!"
echo "  ./run_mac.sh       — start the tray app (scheduler + icon)"
echo "  ./run_once_mac.sh  — run a single price check (for testing)"
