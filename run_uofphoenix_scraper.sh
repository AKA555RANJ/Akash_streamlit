#!/usr/bin/env bash
# Run script for UofPhoenix scraper in GitHub Codespace
# Usage: bash run_uofphoenix_scraper.sh

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
           /usr/share/keyrings/yarnkey.gpg 2>/dev/null || true
sudo apt-get update -q -o Acquire::AllowInsecureRepositories=false \
  -o Dir::Etc::sourcelist="sources.list" \
  -o Dir::Etc::sourcelistd="sources.list.d" 2>/dev/null || \
  sudo apt-get update -q --allow-insecure-repositories || true

sudo apt-get install -y -q xvfb chromium-browser 2>/dev/null || \
  sudo apt-get install -y -q xvfb chromium

CHROME_BIN=$(which chromium-browser 2>/dev/null || which chromium 2>/dev/null || true)
if [ -z "$CHROME_BIN" ]; then
  echo "[ERROR] Could not find chromium. Trying snap..."
  sudo snap install chromium
  CHROME_BIN=$(which chromium 2>/dev/null)
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
  cp -r /tmp/func_timeout-*/func_timeout "$(python3 -c 'import site; print(site.getsitepackages()[0])')/"
fi

# xvfbwrapper stub (we manage Xvfb ourselves)
python3 -c "import xvfbwrapper" 2>/dev/null || python3 -c "
import site, os
stub = '''class Xvfb:
    def __init__(self, *a, **k): pass
    def start(self): pass
    def stop(self): pass
    def __enter__(self): return self
    def __exit__(self, *a): pass
'''
path = os.path.join(site.getsitepackages()[0], 'xvfbwrapper.py')
open(path, 'w').write(stub)
print('    xvfbwrapper stub created')
"

pip install -q flaresolverr --no-deps
echo "    Python deps OK"

# --- 3. Start Xvfb ---
echo ""
echo "[3/5] Starting Xvfb virtual display..."
pkill -f "Xvfb :99" 2>/dev/null || true
sleep 1
Xvfb :99 -screen 0 1280x720x24 -nolisten tcp &
XVFB_PID=$!
sleep 2
echo "    Xvfb PID: $XVFB_PID"

# --- 4. Start FlareSolverr ---
echo ""
echo "[4/5] Starting FlareSolverr..."
pkill -f "flaresolverr" 2>/dev/null || true
sleep 1
DISPLAY=:99 CHROME_EXE_PATH="$CHROME_BIN" HOST=0.0.0.0 PORT=8191 \
  python3 -m flaresolverr > /tmp/flaresolverr.log 2>&1 &
FLARE_PID=$!

# Wait for FlareSolverr to be ready
for i in $(seq 1 20); do
  sleep 2
  STATUS=$(curl -s http://localhost:8191/v1 -X POST \
    -H "Content-Type: application/json" \
    -d '{"cmd":"sessions.list"}' 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('status',''))" 2>/dev/null || true)
  if [ "$STATUS" = "ok" ]; then
    echo "    FlareSolverr ready (attempt $i)"
    break
  fi
  echo "    Waiting for FlareSolverr... ($i/20)"
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
