#!/usr/bin/env bash
# Run script for UofPhoenix scraper in GitHub Codespace
# Usage: bash run_uofphoenix_scraper.sh [--fresh]

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "======================================"
echo " UofPhoenix Scraper - Codespace Setup"
echo "======================================"

# --- 1. System deps (Xvfb + Chromium) ---
echo ""
echo "[1/5] Installing system dependencies..."

# Remove broken Yarn repo that causes GPG errors in Codespaces
sudo rm -f /etc/apt/sources.list.d/yarn.list \
           /etc/apt/sources.list.d/yarn.list.save \
           /usr/share/keyrings/yarnkey.gpg 2>/dev/null || true
# Also kill the yarn entry if it's embedded in sources.list
sudo sed -i '/dl.yarnpkg.com/d' /etc/apt/sources.list 2>/dev/null || true

sudo apt-get update -q 2>&1 | grep -v "^W:\|^E:.*yarn" || true
sudo apt-get install -y -q xvfb

# chromium-browser in Ubuntu 24.04 Codespaces is a snap stub — not usable.
# Install real Chromium via playwright's bundled binary instead.
CHROME_BIN=$(find /root/.cache/ms-playwright /home/*/.cache/ms-playwright \
  -name "chrome" -type f 2>/dev/null | head -1)

if [ -z "$CHROME_BIN" ]; then
  echo "    Installing Playwright + Chromium..."
  pip install -q playwright
  python3 -m playwright install chromium
  CHROME_BIN=$(find /root/.cache/ms-playwright /home/*/.cache/ms-playwright \
    -name "chrome" -type f 2>/dev/null | head -1)
fi

# Install Chrome system library dependencies (libatk, libgbm, etc.)
echo "    Installing Chrome system dependencies..."
sudo python3 -m playwright install-deps chromium 2>&1 | tail -5

if [ -z "$CHROME_BIN" ]; then
  echo "[ERROR] Could not find or install Chromium."
  exit 1
fi
echo "    Chrome binary: $CHROME_BIN"

# --- 2. Python deps ---
echo ""
echo "[2/5] Installing Python dependencies..."
pip install -q requests tqdm bottle waitress prometheus_client DrissionPage nodriver

# func-timeout needs manual install (build issues on some systems)
if ! python3 -c "import func_timeout" 2>/dev/null; then
  pip download func-timeout -d /tmp/ft_dl -q
  tar xzf /tmp/ft_dl/func_timeout-*.tar.gz -C /tmp/
  SITE=$(python3 -c 'import site; print(site.getsitepackages()[0])')
  cp -r /tmp/func_timeout-*/func_timeout "$SITE/"
  echo "    func_timeout installed manually"
fi

# xvfbwrapper stub (we manage Xvfb ourselves)
python3 -c "import xvfbwrapper" 2>/dev/null || python3 -c "
import site, os
stub = 'class Xvfb:\n    def __init__(self, *a, **k): pass\n    def start(self): pass\n    def stop(self): pass\n    def __enter__(self): return self\n    def __exit__(self, *a): pass\n'
path = os.path.join(site.getsitepackages()[0], 'xvfbwrapper.py')
open(path, 'w').write(stub)
print('    xvfbwrapper stub created')
"

pip install -q flaresolverr --no-deps

# Apply all FlareSolverr patches via clean Python script (stealth + fetch_post command)
echo "    Applying FlareSolverr patches..."
python3 "$SCRIPT_DIR/patch_flaresolverr.py"

echo "    Python deps OK"

# --- 3. Start Xvfb ---
echo ""
echo "[3/5] Starting Xvfb virtual display..."
pkill -f "Xvfb :99" 2>/dev/null || true
sleep 1

# Codespaces runs as non-root; Xvfb needs /tmp/.X11-unix to exist first
sudo mkdir -p /tmp/.X11-unix
sudo chmod 1777 /tmp/.X11-unix

Xvfb :99 -screen 0 1920x1080x24 &
XVFB_PID=$!
sleep 3

# Verify the display socket actually exists
if [ ! -S /tmp/.X11-unix/X99 ]; then
  echo "[ERROR] Xvfb display :99 socket not found. Xvfb may have failed."
  echo "        Falling back to Chromium headless mode (--headless=new)..."
  kill $XVFB_PID 2>/dev/null || true
  XVFB_PID=""
  USE_HEADLESS=true
else
  USE_HEADLESS=false
  echo "    Xvfb PID: $XVFB_PID (display :99 OK)"
fi

# --- 4. Start FlareSolverr ---
echo ""
echo "[4/5] Starting FlareSolverr (HEADLESS=false, stealth mode)..."
pkill -f "flaresolverr" 2>/dev/null || true
sleep 1

if [ "$USE_HEADLESS" = "true" ]; then
  DISPLAY="" CHROME_EXE_PATH="$CHROME_BIN" HEADLESS=true \
  HOST=0.0.0.0 PORT=8191 LANG=en-US \
    python3 -m flaresolverr > /tmp/flaresolverr.log 2>&1 &
else
  DISPLAY=:99 CHROME_EXE_PATH="$CHROME_BIN" HEADLESS=false \
  HOST=0.0.0.0 PORT=8191 LANG=en-US \
    python3 -m flaresolverr > /tmp/flaresolverr.log 2>&1 &
fi
FLARE_PID=$!

# Wait for FlareSolverr to be ready (print log every 5 attempts)
STATUS=""
LAST_LOG_LINE=0
for i in $(seq 1 40); do
  sleep 3
  # Print any new log lines so user can see what's happening
  CURRENT_LINES=$(wc -l < /tmp/flaresolverr.log 2>/dev/null || echo 0)
  if [ "$CURRENT_LINES" -gt "$LAST_LOG_LINE" ]; then
    tail -n +"$((LAST_LOG_LINE + 1))" /tmp/flaresolverr.log | sed 's/^/    [flaresolverr] /'
    LAST_LOG_LINE=$CURRENT_LINES
  fi
  # Check if process is still running
  if ! kill -0 $FLARE_PID 2>/dev/null; then
    echo "    [!] FlareSolverr process exited early."
    break
  fi
  STATUS=$(curl -s http://localhost:8191/v1 -X POST \
    -H "Content-Type: application/json" \
    -d '{"cmd":"sessions.list"}' 2>/dev/null \
    | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('status',''))" 2>/dev/null || true)
  if [ "$STATUS" = "ok" ]; then
    echo "    FlareSolverr ready! (attempt $i)"
    break
  fi
done

if [ "$STATUS" != "ok" ]; then
  echo "[ERROR] FlareSolverr did not start. Last logs:"
  tail -30 /tmp/flaresolverr.log
  exit 1
fi
echo ""
echo "    FlareSolverr startup log:"
cat /tmp/flaresolverr.log

# --- 5. Run scraper ---
echo ""
echo "[5/5] Running scraper..."
echo "--------------------------------------"
DISPLAY=:99 python3 uofphoenix_textbook_scraper.py "$@" || true

# Cleanup
echo ""
echo "Cleaning up..."
kill $FLARE_PID 2>/dev/null || true
kill $XVFB_PID 2>/dev/null || true

# --- 6. Push debug output + results to GitHub so they can be reviewed ---
echo ""
echo "[6/6] Pushing debug output and results to GitHub..."

OUTPUT_DATA_DIR="$SCRIPT_DIR/data/university_of_phoenix_arizona__2990835__bks"

# Copy FlareSolverr log into the output dir so it gets committed
cp /tmp/flaresolverr.log "$OUTPUT_DATA_DIR/flaresolverr.log" 2>/dev/null || true

cd "$SCRIPT_DIR"
git config user.email "scraper@codespace" 2>/dev/null || true
git config user.name  "Codespace Scraper"  2>/dev/null || true

# data/ is in .gitignore — force-add the UofPhoenix output specifically
git add -f \
  "$OUTPUT_DATA_DIR/" \
  2>/dev/null || true

if git diff --cached --quiet; then
  echo "    Nothing new to push."
else
  git commit -m "Add scraper debug output and results $(date -u '+%Y-%m-%d %H:%M UTC')"
  git push origin claude/test-scraping-query-NLiow
  echo "    Pushed! Check the data/ folder on the branch."
fi

echo "Done."
