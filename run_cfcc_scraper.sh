#!/usr/bin/env bash
# ============================================================================
# Cape Fear Community College Textbook Scraper — One-command runner
# Usage:  bash run_cfcc_scraper.sh [--fresh] [--headless] [--headed]
#
#   --fresh     Delete existing CSV and start from scratch
#   --headless  Force headless mode (no browser window)
#   --headed    Force headed mode (show browser window, needs display)
#
# If neither --headless nor --headed is given, the scraper auto-detects:
#   - If $DISPLAY is set → headed (xvfb provides a virtual display below)
#   - Otherwise → headless
# ============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== Cape Fear Community College Scraper Setup ==="

# --------------------------------------------------------------------------
# 1. System dependencies (Codespace / Ubuntu / Debian)
# --------------------------------------------------------------------------
install_sys_deps() {
    echo "[1/4] Checking system dependencies..."
    local pkgs_needed=()

    if ! command -v xvfb-run &>/dev/null; then
        pkgs_needed+=(xvfb)
    fi

    # Playwright Chromium needs these libs
    for lib in libatk1.0-0 libatk-bridge2.0-0 libcups2 libxdamage1 libxrandr2 \
               libgbm1 libpango-1.0-0 libcairo2 libnspr4 libnss3; do
        if ! dpkg -s "$lib" &>/dev/null 2>&1; then
            pkgs_needed+=("$lib")
        fi
    done

    # libasound2 was renamed to libasound2t64 on newer Ubuntu/Debian
    if ! dpkg -s libasound2 &>/dev/null 2>&1 && ! dpkg -s libasound2t64 &>/dev/null 2>&1; then
        pkgs_needed+=(libasound2t64)
    fi

    if [ ${#pkgs_needed[@]} -gt 0 ]; then
        echo "    Installing: ${pkgs_needed[*]}"
        sudo apt-get update -qq
        sudo apt-get install -y -qq "${pkgs_needed[@]}"
    else
        echo "    All system deps present."
    fi
}

# --------------------------------------------------------------------------
# 2. Python virtual environment + pip packages
# --------------------------------------------------------------------------
setup_python() {
    echo "[2/4] Setting up Python environment..."
    if [ ! -d ".venv" ]; then
        python3 -m venv .venv
        echo "    Created .venv"
    fi
    source .venv/bin/activate

    pip install --quiet --upgrade pip
    pip install --quiet playwright tqdm
    echo "    Python packages installed."
}

# --------------------------------------------------------------------------
# 3. Playwright browsers
# --------------------------------------------------------------------------
install_browsers() {
    echo "[3/4] Installing Playwright Chromium browser..."
    source .venv/bin/activate

    # Check if a compatible Chromium is already installed
    PW_CACHE="${HOME}/.cache/ms-playwright"
    EXISTING_CHROME=$(find "$PW_CACHE" -path '*/chromium-*/chrome-linux/chrome' 2>/dev/null | sort | tail -1)

    if [ -n "$EXISTING_CHROME" ]; then
        echo "    Found pre-installed Chromium: $EXISTING_CHROME"
        export PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH="$EXISTING_CHROME"
    else
        # Try to install; --with-deps handles system libs on supported distros
        if playwright install chromium --with-deps 2>/dev/null; then
            echo "    Chromium installed via playwright."
        elif playwright install chromium 2>/dev/null; then
            echo "    Chromium installed (without --with-deps)."
        else
            echo "    [WARN] playwright install failed. Will try to use system chromium."
            # Fallback: check for system chromium
            for cmd in chromium-browser chromium google-chrome-stable google-chrome; do
                if command -v "$cmd" &>/dev/null; then
                    export PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH="$(command -v "$cmd")"
                    echo "    Using system browser: $PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH"
                    break
                fi
            done
        fi
    fi

    echo "    Chromium ready."
}

# --------------------------------------------------------------------------
# 4. Run the scraper
# --------------------------------------------------------------------------
run_scraper() {
    echo "[4/4] Running scraper..."
    source .venv/bin/activate

    # Pass through CLI args (--fresh, --headless, --headed)
    ARGS=("$@")

    # If running in a headless environment (no DISPLAY), use xvfb-run
    # to provide a virtual framebuffer — this lets Playwright run in
    # headed mode (better PX evasion) even without a real monitor.
    if [ -z "${DISPLAY:-}" ] && command -v xvfb-run &>/dev/null; then
        echo "    No display detected — using xvfb virtual framebuffer"
        xvfb-run --auto-servernum --server-args="-screen 0 1280x800x24" \
            python3 cape_fear_community_college_textbook_scraper.py "${ARGS[@]}"
    else
        python3 cape_fear_community_college_textbook_scraper.py "${ARGS[@]}"
    fi
}

# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
install_sys_deps
setup_python
install_browsers
echo ""
run_scraper "$@"
