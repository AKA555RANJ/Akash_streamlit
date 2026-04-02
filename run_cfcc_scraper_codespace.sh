#!/usr/bin/env bash
# =============================================================================
# run_cfcc_scraper_codespace.sh
# Cape Fear Community College textbook scraper — Codespace one-shot setup & run
#
# Usage:
#   bash run_cfcc_scraper_codespace.sh           # normal run (resumes if CSV exists)
#   bash run_cfcc_scraper_codespace.sh --fresh   # wipe CSV and start over
#
# Copy-paste this whole file into a GitHub Codespace terminal and it will:
#   1. Install all system dependencies (Xvfb, Chromium libs)
#   2. Install Python packages (playwright, tqdm)
#   3. Install Playwright Chromium browser
#   4. Start a virtual display (Xvfb) so headless=False Chrome can run
#   5. Run the scraper
# =============================================================================

set -euo pipefail

FRESH_FLAG="${1:-}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRAPER="$SCRIPT_DIR/cape_fear_community_college_textbook_scraper.py"

echo "============================================================"
echo " Cape Fear CC Textbook Scraper — Codespace Setup & Run"
echo "============================================================"

# ---------------------------------------------------------------------------
# 1. System packages
# ---------------------------------------------------------------------------
echo ""
echo "[1/5] Installing system packages..."
sudo apt-get update -qq
sudo apt-get install -y -qq \
    xvfb \
    libnss3 \
    libatk-bridge2.0-0 \
    libdrm2 \
    libxkbcommon0 \
    libgbm1 \
    libasound2 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libpango-1.0-0 \
    libcairo2 \
    fonts-liberation \
    2>/dev/null || true
echo "    System packages ready."

# ---------------------------------------------------------------------------
# 2. Python packages
# ---------------------------------------------------------------------------
echo ""
echo "[2/5] Installing Python packages..."
pip install --quiet --upgrade pip
pip install --quiet playwright tqdm

# Also ensure requirements_scraper.txt extras are present (optional)
if [[ -f "$SCRIPT_DIR/requirements_scraper.txt" ]]; then
    pip install --quiet -r "$SCRIPT_DIR/requirements_scraper.txt" || true
fi
echo "    Python packages ready."

# ---------------------------------------------------------------------------
# 3. Playwright browser
# ---------------------------------------------------------------------------
echo ""
echo "[3/5] Installing Playwright Chromium browser..."
python -m playwright install chromium
python -m playwright install-deps chromium 2>/dev/null || true
echo "    Playwright Chromium ready."

# ---------------------------------------------------------------------------
# 4. Virtual display (Xvfb) — needed so headless=False Chrome has a display
# ---------------------------------------------------------------------------
echo ""
echo "[4/5] Starting virtual display (Xvfb on :99)..."

# Kill any leftover Xvfb on :99
pkill -f "Xvfb :99" 2>/dev/null || true
sleep 0.5

Xvfb :99 -screen 0 1280x800x24 &
XVFB_PID=$!
export DISPLAY=:99
sleep 2

if kill -0 "$XVFB_PID" 2>/dev/null; then
    echo "    Xvfb started (PID $XVFB_PID, DISPLAY=:99)"
else
    echo "    [WARN] Xvfb failed to start — scraper will fall back to headless=True"
    export DISPLAY=""
fi

# ---------------------------------------------------------------------------
# 5. Run the scraper
# ---------------------------------------------------------------------------
echo ""
echo "[5/5] Running scraper..."
echo "      Output dir: $SCRIPT_DIR/data/cape_fear_community_college__3055607__bks/"
echo ""

cd "$SCRIPT_DIR"
python "$SCRAPER" $FRESH_FLAG

# Cleanup Xvfb
if kill -0 "$XVFB_PID" 2>/dev/null; then
    kill "$XVFB_PID" 2>/dev/null || true
    echo ""
    echo "[*] Xvfb stopped."
fi

echo ""
echo "============================================================"
echo " Done. Check data/cape_fear_community_college__3055607__bks/"
echo "============================================================"
