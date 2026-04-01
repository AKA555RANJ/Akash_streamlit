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
sudo apt-get install -y -q xvfb chromium-browser 2>/dev/null || \
  sudo apt-get install -y -q xvfb chromium

CHROME_BIN=$(which chromium-browser 2>/dev/null || which chromium 2>/dev/null || true)
if [ -z "$CHROME_BIN" ]; then
  echo "[ERROR] Could not find chromium."
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

# Patch FlareSolverr utils.py to remove bot-detection signals:
#   - Remove --no-zygote (unusual flag, fingerprint-detectable)
#   - Remove --auto-open-devtools-for-tabs (DevTools open = bot signal for PerimeterX)
#   - Add --disable-blink-features=AutomationControlled
FLARE_UTILS=$(python3 -c "import flaresolverr.utils as u; print(u.__file__)")
echo "    Patching $FLARE_UTILS for stealth..."
python3 - "$FLARE_UTILS" <<'PYEOF'
import sys, re

path = sys.argv[1]
src = open(path).read()

# Remove --no-zygote line
src = re.sub(r"\s*options\.set_argument\('--no-zygote'\)[^\n]*\n", "\n", src)

# Remove --auto-open-devtools-for-tabs line
src = re.sub(r"\s*options\.set_argument\(\"--auto-open-devtools-for-tabs\"\)[^\n]*\n", "\n", src)

# Add stealth flags after --use-gl=swiftshader if not already present
if "--disable-blink-features=AutomationControlled" not in src:
    src = src.replace(
        "options.set_argument('--use-gl=swiftshader')",
        "options.set_argument('--use-gl=swiftshader')\n"
        "    options.set_argument('--disable-blink-features=AutomationControlled')\n"
        "    options.set_argument('--disable-features=IsolateOrigins,site-per-process')\n"
        "    options.set_argument('--disable-ipc-flooding-protection')"
    )

open(path, 'w').write(src)
print("    Stealth patch applied OK")
PYEOF

echo "    Python deps OK"

# --- 3. Start Xvfb ---
echo ""
echo "[3/5] Starting Xvfb virtual display..."
pkill -f "Xvfb :99" 2>/dev/null || true
sleep 1
Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp &
XVFB_PID=$!
sleep 2
echo "    Xvfb PID: $XVFB_PID"

# --- 4. Start FlareSolverr ---
echo ""
echo "[4/5] Starting FlareSolverr (HEADLESS=false, stealth mode)..."
pkill -f "flaresolverr" 2>/dev/null || true
sleep 1

DISPLAY=:99 \
CHROME_EXE_PATH="$CHROME_BIN" \
HEADLESS=false \
HOST=0.0.0.0 \
PORT=8191 \
LANG=en-US \
  python3 -m flaresolverr > /tmp/flaresolverr.log 2>&1 &
FLARE_PID=$!

# Wait for FlareSolverr to be ready
STATUS=""
for i in $(seq 1 25); do
  sleep 2
  STATUS=$(curl -s http://localhost:8191/v1 -X POST \
    -H "Content-Type: application/json" \
    -d '{"cmd":"sessions.list"}' 2>/dev/null \
    | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('status',''))" 2>/dev/null || true)
  if [ "$STATUS" = "ok" ]; then
    echo "    FlareSolverr ready (attempt $i)"
    break
  fi
  echo "    Waiting for FlareSolverr... ($i/25)"
done

if [ "$STATUS" != "ok" ]; then
  echo "[ERROR] FlareSolverr did not start. Logs:"
  cat /tmp/flaresolverr.log
  exit 1
fi

# --- 5. Run scraper ---
echo ""
echo "[5/5] Running scraper..."
echo "--------------------------------------"
DISPLAY=:99 python3 uofphoenix_textbook_scraper.py "$@"

# Cleanup
echo ""
echo "Cleaning up..."
kill $FLARE_PID 2>/dev/null || true
kill $XVFB_PID 2>/dev/null || true

echo "Done."
